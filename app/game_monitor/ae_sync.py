from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from app.ae_cli import resolve_ae_cli
from app.bot.content_moderation import (
    analyze_public_message,
    public_message_risk_level,
    public_message_risk_type,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.game_chat_repository import GameChatRepository
from app.vip.ae_sync import DEFAULT_AE_PROJECT_ID
from app.vip.server_merges import canonical_server_id, normalize_server_id
from app.vip.service import load_ae_vip_workbook
from config.settings import BASE_DIR


GAME_CHAT_EVENT = "role_chat"
GAME_CHAT_PROPERTIES = (
    "#event_time",
    {"name": "role_id", "type": "event_property"},
    {"name": "server_id", "type": "event_property"},
    {"name": "server_name", "type": "event_property"},
    {"name": "chat_content", "type": "event_property"},
    {"name": "chat_channel", "type": "event_property"},
    {"name": "chat_type", "type": "event_property"},
)
REQUIRED_COLUMNS = {
    "#event_time",
    "role_id",
    "server_id",
    "server_name",
    "chat_content",
    "chat_channel",
    "chat_type",
}
COLUMN_ALIASES = {
    "#event_time": "#event_time",
    "Event time": "#event_time",
    "事件时间": "#event_time",
    "role_id": "role_id",
    "角色ID": "role_id",
    "server_id": "server_id",
    "区服ID": "server_id",
    "server_name": "server_name",
    "区服名称": "server_name",
    "chat_content": "chat_content",
    "聊天内容": "chat_content",
    "chat_channel": "chat_channel",
    "聊天频道": "chat_channel",
    "chat_type": "chat_type",
    "聊天类型": "chat_type",
}


class AEGameChatSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class AEGameChatSyncResult:
    project_id: int
    range_start: str
    range_end: str
    source_row_count: int
    matched_row_count: int
    active_role_count: int
    risk_row_count: int
    synced_at: str
    sync_run_id: int


Runner = Callable[..., subprocess.CompletedProcess[str]]


class AEGameChatSyncService:
    """Export role_chat details for the active VIP role scope into SQLite."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        project_id: int = DEFAULT_AE_PROJECT_ID,
        cli_executable: str = "ae-cli",
        runner: Runner = subprocess.run,
    ) -> None:
        self.db_path = db_path
        self.project_id = int(project_id)
        self.cli_executable = cli_executable
        self.runner = runner
        self.repository = GameChatRepository(db_path)

    def sync(self, range_start: date, range_end: date) -> AEGameChatSyncResult:
        if range_start > range_end:
            raise AEGameChatSyncError("开始日期不能晚于结束日期。")

        start_text = range_start.isoformat()
        end_text = range_end.isoformat()
        started_at = _utc_now()
        active_role_count = 0
        init_database(self.db_path)
        try:
            role_ids = self._active_role_ids()
            active_role_count = len(role_ids)
            if not role_ids:
                raise AEGameChatSyncError(
                    "没有可用的有效角色快照，请先在 VIP 运营中同步 AE 数据。"
                )

            cli_path = self._resolve_cli()
            self._assert_authenticated(cli_path)
            definition = build_event_detail_definition(
                role_ids,
                range_start=range_start,
                range_end=range_end,
            )
            with tempfile.TemporaryDirectory(prefix="ae-game-chat-") as temp_directory:
                artifact_path = Path(temp_directory) / "game-chat.csv.gz"
                self._export(cli_path, definition, artifact_path)
                raw_rows = read_event_detail_artifact(artifact_path)

            message_rows = build_game_chat_rows(raw_rows, active_role_ids=role_ids)
            finished_at = _utc_now()
            sync_run_id = self.repository.replace_window(
                self.project_id,
                start_text,
                end_text,
                message_rows,
                started_at=started_at,
                finished_at=finished_at,
                source_row_count=len(raw_rows),
                active_role_count=active_role_count,
            )
            return AEGameChatSyncResult(
                project_id=self.project_id,
                range_start=start_text,
                range_end=end_text,
                source_row_count=len(raw_rows),
                matched_row_count=len(message_rows),
                active_role_count=active_role_count,
                risk_row_count=sum(bool(row.get("risk_level")) for row in message_rows),
                synced_at=finished_at,
                sync_run_id=sync_run_id,
            )
        except Exception as exc:
            finished_at = _utc_now()
            message = str(exc) or exc.__class__.__name__
            self.repository.record_failure(
                self.project_id,
                start_text,
                end_text,
                started_at=started_at,
                finished_at=finished_at,
                error_message=message,
                active_role_count=active_role_count,
            )
            if isinstance(exc, AEGameChatSyncError):
                raise
            raise AEGameChatSyncError(message) from exc

    def _active_role_ids(self) -> tuple[str, ...]:
        workbook = load_ae_vip_workbook(self.db_path, self.project_id)
        if workbook is None or workbook.active_df.empty:
            return ()
        values = {
            _clean_identifier(value)
            for value in workbook.active_df["角色ID"].tolist()
            if _clean_identifier(value)
        }
        return tuple(sorted(values))

    def _resolve_cli(self) -> str:
        resolved = resolve_ae_cli(self.cli_executable)
        if not resolved:
            raise AEGameChatSyncError(
                f"找不到 {self.cli_executable}，请先安装 @thinkingai/ae-cli。"
            )
        return resolved

    def _assert_authenticated(self, cli_path: str) -> None:
        completed = self._run([cli_path, "auth", "status"], timeout=60)
        payload = _parse_cli_json(completed.stdout)
        if not payload.get("ok") or not payload.get("data", {}).get("authenticated"):
            raise AEGameChatSyncError("AE CLI 尚未登录，请先执行 ae-cli auth login。")

    def _export(
        self,
        cli_path: str,
        definition: dict[str, Any],
        output_path: Path,
    ) -> None:
        definition_json = json.dumps(definition, ensure_ascii=False, separators=(",", ":"))
        completed = self._run(
            [
                cli_path,
                "analysis",
                "event-detail",
                "export",
                "--project-id",
                str(self.project_id),
                "--definition",
                definition_json,
                "--artifact-format",
                "csv",
                "--output",
                str(output_path),
                "--wait-timeout-seconds",
                "600",
                "--timeout-seconds",
                "21600",
                "--force",
            ],
            timeout=660,
        )
        payload = _parse_cli_json(completed.stdout)
        if not payload.get("ok"):
            detail = payload.get("error", {}).get("message") or "AE 聊天日志导出失败"
            raise AEGameChatSyncError(str(detail))
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise AEGameChatSyncError("AE 导出完成，但没有生成可读取的数据文件。")

    def _run(self, command: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        completed = self.runner(
            list(command),
            cwd=BASE_DIR,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if completed.returncode != 0:
            output = (completed.stdout or completed.stderr or "").strip()
            try:
                payload = _parse_cli_json(output)
                output = str(payload.get("error", {}).get("message") or output)
            except AEGameChatSyncError:
                pass
            raise AEGameChatSyncError(output[-2000:] or "AE CLI 命令执行失败。")
        return completed


def build_event_detail_definition(
    role_ids: Sequence[str],
    *,
    range_start: date,
    range_end: date,
) -> dict[str, Any]:
    return {
        "event": GAME_CHAT_EVENT,
        "time_range": {
            "mode": "absolute",
            "start_time": f"{range_start.isoformat()} 00:00:00",
            "end_time": f"{range_end.isoformat()} 23:59:59",
        },
        "filters": {
            "relation": "and",
            "items": [
                {
                    "field": {"name": "role_id", "type": "event_property"},
                    "operator": "eq",
                    "values": list(role_ids),
                },
                {
                    "field": {"name": "chat_type", "type": "event_property"},
                    "operator": "eq",
                    "values": ["发言"],
                },
            ],
        },
        "properties": list(GAME_CHAT_PROPERTIES),
        "sort": [{"field": "#event_time", "order": "desc"}],
    }


def read_event_detail_artifact(path: str | Path) -> list[dict[str, str]]:
    artifact_path = Path(path)
    with artifact_path.open("rb") as source:
        magic = source.read(2)
    if magic == b"\x1f\x8b":
        with gzip.open(artifact_path, "rb") as source:
            payload = source.read()
    else:
        payload = artifact_path.read_bytes()

    bom = b"\xef\xbb\xbf"
    while payload.startswith(bom):
        payload = payload[len(bom) :]
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8")))
    normalized_rows = [
        {
            COLUMN_ALIASES.get(str(key or "").strip(), str(key or "").strip()): value
            for key, value in row.items()
        }
        for row in reader
    ]
    header = set(normalized_rows[0]) if normalized_rows else {
        COLUMN_ALIASES.get(str(key or "").strip(), str(key or "").strip())
        for key in (reader.fieldnames or ())
    }
    missing = sorted(REQUIRED_COLUMNS - header)
    if missing:
        raise AEGameChatSyncError(f"AE 聊天日志导出缺少字段：{'、'.join(missing)}。")
    return normalized_rows


def build_game_chat_rows(
    raw_rows: Sequence[dict[str, str]],
    *,
    active_role_ids: Sequence[str],
) -> list[dict[str, object]]:
    active_scope = {_clean_identifier(value) for value in active_role_ids}
    unique_rows: dict[str, dict[str, object]] = {}
    for raw in raw_rows:
        role_id = _clean_identifier(raw.get("role_id"))
        content = str(raw.get("chat_content") or "").strip()
        event_time = str(raw.get("#event_time") or "").strip()
        chat_type = str(raw.get("chat_type") or "").strip()
        if role_id not in active_scope or not content or not event_time or chat_type != "发言":
            continue

        source_server_id = _clean_identifier(raw.get("server_id"))
        server_id = canonical_server_id(source_server_id)
        server_name = _canonical_server_name(
            raw.get("server_name"),
            source_server_id=source_server_id,
            canonical_server=server_id,
        )
        chat_channel = str(raw.get("chat_channel") or "").strip()
        moderation = analyze_public_message(content)
        reason = moderation.reason if moderation.should_capture else None
        risk_level = public_message_risk_level(content, reason)
        message_key = _message_key(
            event_time,
            role_id,
            source_server_id,
            chat_channel,
            content,
        )
        unique_rows[message_key] = {
            "message_key": message_key,
            "event_time": event_time,
            "role_id": role_id,
            "server_id": server_id,
            "server_name": server_name,
            "chat_content": content,
            "chat_channel": chat_channel,
            "chat_type": chat_type,
            "risk_level": risk_level,
            "risk_type": public_message_risk_type(reason) if risk_level else None,
            "risk_reason": reason,
            "source_event": GAME_CHAT_EVENT,
        }
    return sorted(unique_rows.values(), key=lambda row: str(row["event_time"]))


def _message_key(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _clean_identifier(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _canonical_server_name(
    value: object,
    *,
    source_server_id: str,
    canonical_server: str,
) -> str:
    name = str(value or "").strip()
    if canonical_server and canonical_server != source_server_id:
        normalized_name = normalize_server_id(name)
        if not name or normalized_name == source_server_id:
            return f"S{canonical_server}"
    return name


def _parse_cli_json(output: str) -> dict[str, Any]:
    text = (output or "").strip()
    start = text.find("{")
    if start < 0:
        raise AEGameChatSyncError("AE CLI 未返回可解析的 JSON。")
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError as exc:
        raise AEGameChatSyncError("AE CLI 返回了无法解析的 JSON。") from exc
    if not isinstance(payload, dict):
        raise AEGameChatSyncError("AE CLI 返回结构异常。")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
