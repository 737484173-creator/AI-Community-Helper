from __future__ import annotations

import csv
import gzip
import io
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from app.ae_cli import resolve_ae_cli
from app.database.migrations.init_db import init_database
from app.database.repositories.vip_ae_repository import AEVIPSnapshotRepository
from app.vip.server_merges import canonical_server_id
from app.vip.utils.excel_reader import _infer_server_type
from config.settings import BASE_DIR


DEFAULT_AE_PROJECT_ID = 24
DEFAULT_MINIMUM_PAYMENT_USD = 1000.0

_PAYMENT_METRIC = {
    "event": "role_pay",
    "aggregation": "sum",
    "property": "#vp@currency_type__currency_amount__USD",
    "filters": [
        {
            "field": {"name": "is_sandbox", "type": "event_property"},
            "operator": "eq",
            "values": ["0"],
        }
    ],
    "relation": "and",
}

CUMULATIVE_PROFILE_DEFINITION = {
    "time_range": {"mode": "start_to_yesterday", "start_time": "2023-01-01"},
    "time_particle_size": "total",
    "metrics": [_PAYMENT_METRIC],
    "groups": [
        {"field": {"name": "#account_id", "type": "user_property"}},
        {"field": {"name": "role_name", "type": "user_property"}},
        {"field": {"name": "cur_server_id", "type": "user_property"}},
        {"field": {"name": "cur_server_name", "type": "user_property"}},
        {"field": {"name": "last_login_time", "type": "user_property"}},
        {"field": {"name": "#vp@cps_group", "type": "user_property"}},
    ],
    "relation": "and",
}

WEEKLY_PAYMENT_DEFINITION = {
    "time_range": {"mode": "previous", "unit": "day", "value": 7},
    "time_particle_size": "total",
    "metrics": [_PAYMENT_METRIC],
    "groups": [
        {"field": {"name": "#account_id", "type": "user_property"}},
    ],
    "relation": "and",
}

FOURTEEN_DAY_PAYMENT_DEFINITION = {
    **WEEKLY_PAYMENT_DEFINITION,
    "time_range": {"mode": "previous", "unit": "day", "value": 14},
}

ROLLING_28_DAY_PAYMENT_DEFINITION = {
    **WEEKLY_PAYMENT_DEFINITION,
    # Pull five weeks so the current seven days can be removed locally. The
    # stored weekly average therefore represents the *preceding* 28 days and
    # does not dilute the comparison with the current week itself.
    "time_range": {"mode": "previous", "unit": "day", "value": 35},
}


class AEVIPSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class AEVIPSyncResult:
    project_id: int
    source_row_count: int
    vip_row_count: int
    cumulative_window: str
    weekly_window: str
    previous_week_window: str
    rolling_28d_window: str
    synced_at: str
    sync_run_id: int


Runner = Callable[..., subprocess.CompletedProcess[str]]


class AEVIPSyncService:
    """Export VIP source data through AE CLI and atomically refresh SQLite."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        project_id: int = DEFAULT_AE_PROJECT_ID,
        minimum_payment_usd: float = DEFAULT_MINIMUM_PAYMENT_USD,
        cli_executable: str = "ae-cli",
        runner: Runner = subprocess.run,
    ) -> None:
        self.db_path = db_path
        self.project_id = int(project_id)
        self.minimum_payment_usd = float(minimum_payment_usd)
        self.cli_executable = cli_executable
        self.runner = runner
        self.repository = AEVIPSnapshotRepository(db_path)

    def sync(self) -> AEVIPSyncResult:
        init_database(self.db_path)
        started_at = _utc_now()
        try:
            cli_path = self._resolve_cli()
            self._assert_authenticated(cli_path)
            with tempfile.TemporaryDirectory(prefix="ae-vip-") as temp_directory:
                temp_path = Path(temp_directory)
                cumulative_path = temp_path / "cumulative-profile.csv.gz"
                weekly_path = temp_path / "weekly-payment.csv.gz"
                fortnight_path = temp_path / "fortnight-payment.csv.gz"
                rolling_28d_path = temp_path / "rolling-28d-payment.csv.gz"
                self._export(cli_path, CUMULATIVE_PROFILE_DEFINITION, cumulative_path)
                self._export(cli_path, WEEKLY_PAYMENT_DEFINITION, weekly_path)
                self._export(cli_path, FOURTEEN_DAY_PAYMENT_DEFINITION, fortnight_path)
                self._export(cli_path, ROLLING_28_DAY_PAYMENT_DEFINITION, rolling_28d_path)

                cumulative_rows = read_ae_csv_artifact(cumulative_path, minimum_columns=8)
                weekly_rows = read_ae_csv_artifact(weekly_path, minimum_columns=3)
                fortnight_rows = read_ae_csv_artifact(fortnight_path, minimum_columns=3)
                rolling_28d_rows = read_ae_csv_artifact(rolling_28d_path, minimum_columns=3)
                (
                    snapshot_rows,
                    cumulative_window,
                    weekly_window,
                    previous_week_window,
                    rolling_28d_window,
                ) = build_snapshot_rows(
                    cumulative_rows,
                    weekly_rows,
                    fortnight_rows,
                    rolling_28d_rows,
                    minimum_payment_usd=self.minimum_payment_usd,
                )

            if not cumulative_rows:
                raise AEVIPSyncError("AE 累计充值导出为空，已保留上一版快照。")
            if not snapshot_rows:
                raise AEVIPSyncError(
                    f"AE 导出中没有累计充值达到 {self.minimum_payment_usd:g} 美元的玩家，"
                    "已保留上一版快照。"
                )

            finished_at = _utc_now()
            sync_run_id = self.repository.replace_snapshot(
                self.project_id,
                snapshot_rows,
                started_at=started_at,
                finished_at=finished_at,
                source_row_count=len(cumulative_rows),
                cumulative_window=cumulative_window,
                weekly_window=weekly_window,
                previous_week_window=previous_week_window,
                rolling_28d_window=rolling_28d_window,
            )
            return AEVIPSyncResult(
                project_id=self.project_id,
                source_row_count=len(cumulative_rows),
                vip_row_count=len(snapshot_rows),
                cumulative_window=cumulative_window,
                weekly_window=weekly_window,
                previous_week_window=previous_week_window,
                rolling_28d_window=rolling_28d_window,
                synced_at=finished_at,
                sync_run_id=sync_run_id,
            )
        except Exception as exc:
            finished_at = _utc_now()
            message = str(exc) or exc.__class__.__name__
            self.repository.record_failure(
                self.project_id,
                started_at=started_at,
                finished_at=finished_at,
                error_message=message,
            )
            if isinstance(exc, AEVIPSyncError):
                raise
            raise AEVIPSyncError(message) from exc

    def _resolve_cli(self) -> str:
        resolved = resolve_ae_cli(self.cli_executable)
        if not resolved:
            raise AEVIPSyncError(
                f"找不到 {self.cli_executable}，请先安装 @thinkingai/ae-cli。"
            )
        return resolved

    def _assert_authenticated(self, cli_path: str) -> None:
        completed = self._run([cli_path, "auth", "status"], timeout=60)
        payload = _parse_cli_json(completed.stdout)
        if not payload.get("ok") or not payload.get("data", {}).get("authenticated"):
            raise AEVIPSyncError("AE CLI 尚未登录，请先执行 ae-cli auth login。")

    def _export(self, cli_path: str, definition: dict[str, Any], output_path: Path) -> None:
        definition_json = json.dumps(definition, ensure_ascii=False, separators=(",", ":"))
        completed = self._run(
            [
                cli_path,
                "analysis",
                "adhoc",
                "export",
                "--project-id",
                str(self.project_id),
                "--model-type",
                "event",
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
            detail = payload.get("error", {}).get("message") or "AE 导出失败"
            raise AEVIPSyncError(str(detail))
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise AEVIPSyncError("AE 导出完成，但没有生成可读取的数据文件。")

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
            except AEVIPSyncError:
                pass
            raise AEVIPSyncError(output[-2000:] or "AE CLI 命令执行失败。")
        return completed


def read_ae_csv_artifact(path: str | Path, *, minimum_columns: int) -> list[list[str]]:
    artifact_path = Path(path)
    with artifact_path.open("rb") as source:
        magic = source.read(2)
    opener = gzip.open if magic == b"\x1f\x8b" else Path.open
    if opener is gzip.open:
        with gzip.open(artifact_path, "rb") as source:
            payload = source.read()
    else:
        payload = artifact_path.read_bytes()

    bom = b"\xef\xbb\xbf"
    while payload.startswith(bom):
        payload = payload[len(bom) :]
    reader = csv.reader(io.StringIO(payload.decode("utf-8")))
    try:
        header = next(reader)
    except StopIteration:
        return []
    if len(header) < minimum_columns:
        raise AEVIPSyncError(
            f"AE 导出列数异常：期望至少 {minimum_columns} 列，实际 {len(header)} 列。"
        )
    return [row for row in reader if row and any(cell.strip() for cell in row)]


def build_snapshot_rows(
    cumulative_rows: Sequence[Sequence[str]],
    weekly_rows: Sequence[Sequence[str]],
    fortnight_rows: Sequence[Sequence[str]] = (),
    rolling_28d_rows: Sequence[Sequence[str]] = (),
    *,
    minimum_payment_usd: float = DEFAULT_MINIMUM_PAYMENT_USD,
) -> tuple[list[dict[str, object]], str, str, str, str]:
    profiles: dict[str, dict[str, object]] = {}
    cumulative_window = ""
    for row in cumulative_rows:
        if len(row) < 8:
            continue
        cumulative_window = cumulative_window or _clean_text(row[0])
        role_id = _clean_identifier(row[1])
        if not role_id:
            continue
        total_payment = _coerce_float(row[7])
        candidate = {
            "role_id": role_id,
            "role_name": _clean_text(row[2]),
            "server_id": canonical_server_id(_clean_identifier(row[3])),
            "server_name": _clean_text(row[4]),
            "last_login_time": _clean_text(row[5]),
            "cps_group": _clean_text(row[6]),
            "total_payment_amount": total_payment,
        }
        existing = profiles.get(role_id)
        if existing is None:
            profiles[role_id] = candidate
            continue
        maximum_total = max(float(existing["total_payment_amount"]), total_payment)
        if _profile_rank(candidate) > _profile_rank(existing):
            candidate["total_payment_amount"] = maximum_total
            profiles[role_id] = candidate
        else:
            existing["total_payment_amount"] = maximum_total

    weekly_by_role, weekly_window = _payment_rows_by_role(weekly_rows)
    fortnight_by_role, fortnight_window = _payment_rows_by_role(fortnight_rows)
    rolling_28d_by_role, rolling_28d_window = _payment_rows_by_role(rolling_28d_rows)

    snapshot: list[dict[str, object]] = []
    for role_id, profile in profiles.items():
        total_payment = float(profile["total_payment_amount"])
        if total_payment < minimum_payment_usd:
            continue
        server_id = str(profile["server_id"])
        cps_group = str(profile["cps_group"])
        current_week = weekly_by_role.get(role_id, 0.0)
        fortnight_total = fortnight_by_role.get(role_id, 0.0)
        rolling_35d_total = rolling_28d_by_role.get(role_id, 0.0)
        profile.update(
            payment_7d_amount=current_week,
            payment_previous_7d_amount=(
                max(float(fortnight_total) - current_week, 0.0)
            ),
            payment_28d_weekly_avg=(
                max(float(rolling_35d_total) - current_week, 0.0) / 4.0
            ),
            server_type=_infer_server_type(server_id),
            user_source="CPS" if cps_group else "自然量",
        )
        snapshot.append(profile)

    snapshot.sort(key=lambda item: (-float(item["total_payment_amount"]), str(item["role_id"])))
    previous_week_window = (
        f"{fortnight_window}（扣除近7日）" if fortnight_window else ""
    )
    preceding_28d_window = (
        f"{rolling_28d_window}（扣除近7日）" if rolling_28d_window else ""
    )
    return (
        snapshot,
        cumulative_window,
        weekly_window,
        previous_week_window,
        preceding_28d_window,
    )


def _payment_rows_by_role(
    rows: Sequence[Sequence[str]],
) -> tuple[dict[str, float], str]:
    values: dict[str, float] = {}
    window = ""
    for row in rows:
        if len(row) < 3:
            continue
        window = window or _clean_text(row[0])
        role_id = _clean_identifier(row[1])
        if not role_id:
            continue
        values[role_id] = max(values.get(role_id, 0.0), _coerce_float(row[2]))
    return values, window


def _profile_rank(profile: dict[str, object]) -> tuple[str, int]:
    last_login = str(profile.get("last_login_time") or "")
    completeness = sum(
        bool(profile.get(field))
        for field in ("role_name", "server_id", "server_name", "last_login_time", "cps_group")
    )
    return last_login, completeness


def _clean_text(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"(null)", "null", "none", "nan", "nat"}:
        return ""
    return text


def _clean_identifier(value: object) -> str:
    return _clean_text(value).removesuffix(".0")


def _coerce_float(value: object) -> float:
    text = _clean_text(value).replace(",", "").replace("$", "")
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def _parse_cli_json(output: str) -> dict[str, Any]:
    text = (output or "").strip()
    start = text.find("{")
    if start < 0:
        raise AEVIPSyncError("AE CLI 未返回可解析的 JSON。")
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError as exc:
        raise AEVIPSyncError("AE CLI 返回了无法解析的 JSON。") from exc
    if not isinstance(payload, dict):
        raise AEVIPSyncError("AE CLI 返回结构异常。")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
