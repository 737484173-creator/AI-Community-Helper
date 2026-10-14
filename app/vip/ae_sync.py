from __future__ import annotations

import csv
import gzip
import io
import json
import re
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.ae_cli import resolve_ae_cli
from app.database.migrations.init_db import init_database
from app.database.repositories.vip_ae_repository import AEVIPSnapshotRepository
from app.vip.server_merges import canonical_server_id
from app.vip.item_catalog import ItemCatalog, classify_consumption_category, load_item_catalog
from app.vip.utils.excel_reader import _infer_server_type
from config.settings import BASE_DIR


DEFAULT_AE_PROJECT_ID = 24
DEFAULT_MINIMUM_PAYMENT_USD = 1000.0
DRAGON_COIN_ITEM_ID = "20000064"
DRAGON_COIN_NAME = "龙币"

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

PROFILE_POWER_FIELDS = (
    "build_fp",
    "tech_fp",
    "soldier_fp",
    "beast_fp",
    "hero_fp",
    "hiryu_fp",
    "com_fp",
    "leg_tech_fp",
    "cur_fp",
)

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
        *[
            {"field": {"name": field, "type": "user_property"}}
            for field in PROFILE_POWER_FIELDS
        ],
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


def _purchase_definition(time_range: dict[str, Any]) -> dict[str, Any]:
    return {
        "time_range": time_range,
        "time_particle_size": "total",
        "metrics": [
            {
                "event": "role_pay",
                "aggregation": "total_count",
                "filters": _PAYMENT_METRIC["filters"],
                "relation": "and",
            },
            _PAYMENT_METRIC,
            {
                "event": "role_pay",
                "aggregation": "sum",
                "property": "giftbox_detail.amount",
                "filters": _PAYMENT_METRIC["filters"],
                "relation": "and",
            },
        ],
        "groups": [
            {"field": {"name": "#account_id", "type": "user_property"}},
            {"field": {"name": "giftbox_id", "type": "event_property"}},
            {"field": {"name": "giftbox_name", "type": "event_property"}},
            {"field": {"name": "activity_id", "type": "event_property"}},
            {"field": {"name": "activity_name", "type": "event_property"}},
            {"field": {"name": "giftbox_detail.id", "type": "event_property"}},
            {"field": {"name": "giftbox_detail.name", "type": "event_property"}},
        ],
        "relation": "and",
    }


PURCHASE_LIFETIME_DEFINITION = _purchase_definition(
    {"mode": "start_to_yesterday", "start_time": "2023-01-01"}
)
PURCHASE_7D_DEFINITION = _purchase_definition(
    {"mode": "previous", "unit": "day", "value": 7}
)
PURCHASE_14D_DEFINITION = _purchase_definition(
    {"mode": "previous", "unit": "day", "value": 14}
)
PURCHASE_RECENT_DEFINITION = _purchase_definition(
    {"mode": "previous", "unit": "day", "value": 30}
)


ITEM_DETAIL_PROPERTIES: list[str | dict[str, str]] = [
    "#event_time",
    {"name": "role_id", "type": "event_property"},
    {"name": "server_id", "type": "event_property"},
    {"name": "item_id", "type": "event_property"},
    {"name": "item_id@item_name_2", "type": "event_property"},
    {"name": "old_num", "type": "event_property"},
    {"name": "new_num", "type": "event_property"},
    {"name": "var_num", "type": "event_property"},
    {"name": "buy_id", "type": "event_property"},
    {"name": "buy_num", "type": "event_property"},
    {"name": "use_id", "type": "event_property"},
    {"name": "use_num", "type": "event_property"},
    {"name": "way_id", "type": "event_property"},
    {"name": "way_id@way_name", "type": "event_property"},
]


def _item_detail_definition(
    time_range: dict[str, Any],
    role_ids: set[str],
    *,
    kind: str,
) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [
        {
            "field": {"name": "role_id", "type": "event_property"},
            "operator": "eq",
            "values": sorted(role_ids),
        }
    ]
    if kind == "dragon_coin_spend":
        filters.extend(
            [
                {
                    "field": {"name": "item_id", "type": "event_property"},
                    "operator": "eq",
                    "values": [DRAGON_COIN_ITEM_ID],
                },
                {
                    "field": {"name": "var_num", "type": "event_property"},
                    "operator": "lt",
                    "values": ["0"],
                },
                {
                    "field": {"name": "way_id@way_name", "type": "event_property"},
                    "operator": "eq",
                    "values": ["龙币购买消耗"],
                },
            ]
        )
    elif kind == "paid_reward":
        filters.extend(
            [
                {
                    "field": {"name": "var_num", "type": "event_property"},
                    "operator": "gt",
                    "values": ["0"],
                },
                {
                    "field": {"name": "way_id@way_name", "type": "event_property"},
                    "operator": "contains",
                    "values": ["[付费]"],
                },
            ]
        )
    else:
        raise ValueError(f"Unsupported Item detail kind: {kind}")
    return {
        "event": "Item",
        "time_range": time_range,
        "filters": {"relation": "and", "items": filters},
        "properties": ITEM_DETAIL_PROPERTIES,
        "sort": [{"field": "#event_time", "order": "desc"}],
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
    purchase_package_count: int
    purchase_lifetime_window: str
    purchase_7d_window: str
    purchase_14d_window: str
    purchase_recent_window: str
    synced_at: str
    sync_run_id: int
    dragon_coin_warning: str = ""


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
        dragon_coin_warning = ""
        cached_coin_packages = [
            dict(row)
            for row in self.repository.list_purchase_packages_by_channel(
                self.project_id,
                "dragon_coin",
            )
        ]
        try:
            cli_path = self._resolve_cli()
            self._assert_authenticated(cli_path)
            with tempfile.TemporaryDirectory(prefix="ae-vip-") as temp_directory:
                temp_path = Path(temp_directory)
                cumulative_path = temp_path / "cumulative-profile.csv.gz"
                weekly_path = temp_path / "weekly-payment.csv.gz"
                fortnight_path = temp_path / "fortnight-payment.csv.gz"
                rolling_28d_path = temp_path / "rolling-28d-payment.csv.gz"
                purchase_lifetime_path = temp_path / "purchase-lifetime.csv.gz"
                purchase_7d_path = temp_path / "purchase-7d.csv.gz"
                purchase_14d_path = temp_path / "purchase-14d.csv.gz"
                purchase_recent_path = temp_path / "purchase-recent.csv.gz"
                coin_spend_lifetime_path = temp_path / "coin-spend-lifetime.csv.gz"
                coin_reward_lifetime_path = temp_path / "coin-reward-lifetime.csv.gz"
                coin_spend_recent_path = temp_path / "coin-spend-recent.csv.gz"
                coin_reward_recent_path = temp_path / "coin-reward-recent.csv.gz"
                self._export(cli_path, CUMULATIVE_PROFILE_DEFINITION, cumulative_path)
                self._export(cli_path, WEEKLY_PAYMENT_DEFINITION, weekly_path)
                self._export(cli_path, FOURTEEN_DAY_PAYMENT_DEFINITION, fortnight_path)
                self._export(cli_path, ROLLING_28_DAY_PAYMENT_DEFINITION, rolling_28d_path)
                self._export(cli_path, PURCHASE_LIFETIME_DEFINITION, purchase_lifetime_path)
                self._export(cli_path, PURCHASE_7D_DEFINITION, purchase_7d_path)
                self._export(cli_path, PURCHASE_14D_DEFINITION, purchase_14d_path)
                self._export(cli_path, PURCHASE_RECENT_DEFINITION, purchase_recent_path)

                cumulative_rows = read_ae_csv_artifact(cumulative_path, minimum_columns=17)
                weekly_rows = read_ae_csv_artifact(weekly_path, minimum_columns=3)
                fortnight_rows = read_ae_csv_artifact(fortnight_path, minimum_columns=3)
                rolling_28d_rows = read_ae_csv_artifact(rolling_28d_path, minimum_columns=3)
                purchase_lifetime_rows = read_ae_csv_artifact(
                    purchase_lifetime_path,
                    minimum_columns=11,
                )
                purchase_7d_rows = read_ae_csv_artifact(
                    purchase_7d_path,
                    minimum_columns=11,
                )
                purchase_14d_rows = read_ae_csv_artifact(
                    purchase_14d_path,
                    minimum_columns=11,
                )
                purchase_recent_rows = read_ae_csv_artifact(
                    purchase_recent_path,
                    minimum_columns=11,
                )
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
                role_ids = {str(row["role_id"]) for row in snapshot_rows}
                item_catalog = load_item_catalog()
                lifetime_packages, purchase_lifetime_window = build_purchase_package_rows(
                    purchase_lifetime_rows,
                    window_key="lifetime",
                    allowed_role_ids=role_ids,
                    item_catalog=item_catalog,
                )
                seven_day_packages, purchase_7d_window = build_purchase_package_rows(
                    purchase_7d_rows,
                    window_key="recent_7d",
                    allowed_role_ids=role_ids,
                    item_catalog=item_catalog,
                )
                fourteen_day_packages, purchase_14d_window = build_purchase_package_rows(
                    purchase_14d_rows,
                    window_key="recent_14d",
                    allowed_role_ids=role_ids,
                    item_catalog=item_catalog,
                )
                recent_packages, purchase_recent_window = build_purchase_package_rows(
                    purchase_recent_rows,
                    window_key="recent_30d",
                    allowed_role_ids=role_ids,
                    item_catalog=item_catalog,
                )
                # AE aggregate exports contain no data row when the whole
                # project has zero purchases. Preserve the completed window
                # label so the UI can distinguish a true zero from no sync.
                for window_key, current_label in (
                    ("lifetime", purchase_lifetime_window),
                    ("recent_7d", purchase_7d_window),
                    ("recent_14d", purchase_14d_window),
                    ("recent_30d", purchase_recent_window),
                ):
                    if current_label:
                        continue
                    _, fallback_label = _item_absolute_time_range(window_key=window_key)
                    if window_key == "lifetime":
                        purchase_lifetime_window = fallback_label
                    elif window_key == "recent_7d":
                        purchase_7d_window = fallback_label
                    elif window_key == "recent_14d":
                        purchase_14d_window = fallback_label
                    else:
                        purchase_recent_window = fallback_label
                coin_detail_rows: tuple[list[dict[str, str]], ...] = ([], [], [], [])
                try:
                    lifetime_range, lifetime_coin_window = _item_absolute_time_range(
                        window_key="lifetime"
                    )
                    recent_range, recent_coin_window = _item_absolute_time_range(
                        window_key="recent_30d"
                    )
                    seven_day_range, seven_day_coin_window = _item_absolute_time_range(
                        window_key="recent_7d"
                    )
                    fourteen_day_range, fourteen_day_coin_window = _item_absolute_time_range(
                        window_key="recent_14d"
                    )
                    for detail_path, detail_definition in (
                        (
                            coin_spend_lifetime_path,
                            _item_detail_definition(
                                lifetime_range, role_ids, kind="dragon_coin_spend"
                            ),
                        ),
                        (
                            coin_reward_lifetime_path,
                            _item_detail_definition(
                                lifetime_range, role_ids, kind="paid_reward"
                            ),
                        ),
                        (
                            coin_spend_recent_path,
                            _item_detail_definition(
                                recent_range, role_ids, kind="dragon_coin_spend"
                            ),
                        ),
                        (
                            coin_reward_recent_path,
                            _item_detail_definition(
                                recent_range, role_ids, kind="paid_reward"
                            ),
                        ),
                    ):
                        self._export_event_detail(cli_path, detail_definition, detail_path)

                    coin_detail_rows = (
                        read_ae_csv_dict_artifact(coin_spend_lifetime_path),
                        read_ae_csv_dict_artifact(coin_reward_lifetime_path),
                        read_ae_csv_dict_artifact(coin_spend_recent_path),
                        read_ae_csv_dict_artifact(coin_reward_recent_path),
                    )
                    coin_lifetime_packages = build_dragon_coin_package_rows(
                        coin_detail_rows[0],
                        coin_detail_rows[1],
                        window_key="lifetime",
                        window_label=lifetime_coin_window,
                        allowed_role_ids=role_ids,
                        item_catalog=item_catalog,
                    )
                    coin_recent_packages = build_dragon_coin_package_rows(
                        coin_detail_rows[2],
                        coin_detail_rows[3],
                        window_key="recent_30d",
                        window_label=recent_coin_window,
                        allowed_role_ids=role_ids,
                        item_catalog=item_catalog,
                    )
                    coin_seven_day_packages = build_dragon_coin_package_rows(
                        _filter_detail_rows_for_range(coin_detail_rows[2], seven_day_range),
                        _filter_detail_rows_for_range(coin_detail_rows[3], seven_day_range),
                        window_key="recent_7d",
                        window_label=seven_day_coin_window,
                        allowed_role_ids=role_ids,
                        item_catalog=item_catalog,
                    )
                    coin_fourteen_day_packages = build_dragon_coin_package_rows(
                        _filter_detail_rows_for_range(coin_detail_rows[2], fourteen_day_range),
                        _filter_detail_rows_for_range(coin_detail_rows[3], fourteen_day_range),
                        window_key="recent_14d",
                        window_label=fourteen_day_coin_window,
                        allowed_role_ids=role_ids,
                        item_catalog=item_catalog,
                    )
                except AEVIPSyncError as coin_exc:
                    coin_lifetime_packages = []
                    coin_recent_packages = []
                    coin_seven_day_packages = []
                    coin_fourteen_day_packages = []
                    for cached_package in cached_coin_packages:
                        if str(cached_package.get("role_id") or "") not in role_ids:
                            continue
                        if str(cached_package.get("window_key") or "") == "lifetime":
                            coin_lifetime_packages.append(cached_package)
                        elif str(cached_package.get("window_key") or "") == "recent_30d":
                            coin_recent_packages.append(cached_package)
                        elif str(cached_package.get("window_key") or "") == "recent_7d":
                            coin_seven_day_packages.append(cached_package)
                        elif str(cached_package.get("window_key") or "") == "recent_14d":
                            coin_fourteen_day_packages.append(cached_package)
                    fallback = (
                        "已沿用 "
                        f"{len(coin_lifetime_packages) + len(coin_recent_packages) + len(coin_seven_day_packages) + len(coin_fourteen_day_packages):,} 条缓存记录"
                        if coin_lifetime_packages or coin_recent_packages or coin_seven_day_packages or coin_fourteen_day_packages
                        else "暂无可沿用的龙币记录"
                    )
                    dragon_coin_warning = (
                        f"龙币 Item 明细同步失败，{fallback}：{coin_exc}"
                    )
                purchase_packages = [
                    *lifetime_packages,
                    *seven_day_packages,
                    *fourteen_day_packages,
                    *recent_packages,
                    *coin_lifetime_packages,
                    *coin_seven_day_packages,
                    *coin_fourteen_day_packages,
                    *coin_recent_packages,
                ]
                purchase_source_row_count = sum(
                    len(rows)
                    for rows in (
                        purchase_lifetime_rows,
                        purchase_7d_rows,
                        purchase_14d_rows,
                        purchase_recent_rows,
                        *coin_detail_rows,
                    )
                )

            finished_at = _utc_now()
            sync_run_id = self.repository.replace_snapshot(
                self.project_id,
                snapshot_rows,
                purchase_rows=purchase_packages,
                started_at=started_at,
                finished_at=finished_at,
                source_row_count=len(cumulative_rows),
                cumulative_window=cumulative_window,
                weekly_window=weekly_window,
                previous_week_window=previous_week_window,
                rolling_28d_window=rolling_28d_window,
                purchase_source_row_count=purchase_source_row_count,
                purchase_lifetime_window=purchase_lifetime_window,
                purchase_7d_window=purchase_7d_window,
                purchase_14d_window=purchase_14d_window,
                purchase_recent_window=purchase_recent_window,
            )
            return AEVIPSyncResult(
                project_id=self.project_id,
                source_row_count=len(cumulative_rows),
                vip_row_count=len(snapshot_rows),
                cumulative_window=cumulative_window,
                weekly_window=weekly_window,
                previous_week_window=previous_week_window,
                rolling_28d_window=rolling_28d_window,
                purchase_package_count=len(purchase_packages),
                purchase_lifetime_window=purchase_lifetime_window,
                purchase_7d_window=purchase_7d_window,
                purchase_14d_window=purchase_14d_window,
                purchase_recent_window=purchase_recent_window,
                synced_at=finished_at,
                sync_run_id=sync_run_id,
                dragon_coin_warning=dragon_coin_warning,
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

    def _export_event_detail(
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
            detail = payload.get("error", {}).get("message") or "AE Item 明细导出失败"
            raise AEVIPSyncError(str(detail))
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise AEVIPSyncError("AE Item 明细导出完成，但没有生成可读取的文件。")

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
    payload = _read_artifact_bytes(path)
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


def read_ae_csv_dict_artifact(path: str | Path) -> list[dict[str, str]]:
    payload = _read_artifact_bytes(path)
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8")))
    if not reader.fieldnames:
        return []
    return [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        for row in reader
        if row and any(str(value or "").strip() for value in row.values())
    ]


def _read_artifact_bytes(path: str | Path) -> bytes:
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
    return payload


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
        has_power_fields = len(row) >= 17
        total_payment_index = 16 if has_power_fields else 7
        total_payment = _coerce_float(row[total_payment_index])
        candidate = {
            "role_id": role_id,
            "role_name": _clean_text(row[2]),
            "server_id": canonical_server_id(_clean_identifier(row[3])),
            "server_name": _clean_text(row[4]),
            "last_login_time": _clean_text(row[5]),
            "cps_group": _clean_text(row[6]),
            "total_payment_amount": total_payment,
            **{
                field: _coerce_optional_float(row[7 + offset])
                if has_power_fields
                else None
                for offset, field in enumerate(PROFILE_POWER_FIELDS)
            },
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


def build_purchase_package_rows(
    rows: Sequence[Sequence[str]],
    *,
    window_key: str,
    allowed_role_ids: set[str] | None = None,
    item_catalog: ItemCatalog | None = None,
) -> tuple[list[dict[str, object]], str]:
    catalog = item_catalog or ItemCatalog({}, {}, None)
    packages: dict[tuple[str, str], dict[str, Any]] = {}
    window_label = ""
    for row in rows:
        if len(row) < 9:
            continue
        window_label = window_label or _clean_text(row[0])
        role_id = _clean_identifier(row[1])
        if not role_id or (allowed_role_ids is not None and role_id not in allowed_role_ids):
            continue
        giftbox_id = _clean_identifier(row[2])
        giftbox_name = _clean_text(row[3])
        if len(row) >= 11:
            activity_id = _clean_identifier(row[4])
            activity_name = _clean_text(row[5])
            item_id = _clean_identifier(row[6])
            item_name = _clean_text(row[7]) or catalog.items.get(item_id, "")
            purchase_count = _coerce_float(row[8])
            payment_amount = _coerce_float(row[9])
            item_amount = _coerce_float(row[10])
        else:
            activity_id = ""
            activity_name = ""
            item_id = _clean_identifier(row[4])
            item_name = _clean_text(row[5]) or catalog.items.get(item_id, "")
            purchase_count = _coerce_float(row[6])
            payment_amount = _coerce_float(row[7])
            item_amount = _coerce_float(row[8])
        giftbox_name = (
            giftbox_name
            or catalog.gifts.get(giftbox_id, "")
            or activity_name
        )
        giftbox_name = _normalize_dragon_coin_label(giftbox_name)
        package_id = giftbox_id or activity_id
        if not package_id and not giftbox_name:
            # Without a package identity the payment metric repeats for every
            # nested item row, so it cannot be de-duplicated safely.
            continue
        stable_giftbox_id = (
            f"{package_id}::{giftbox_name}"
            if package_id and giftbox_name
            else package_id or f"name:{giftbox_name or item_id or 'unknown'}"
        )
        key = (role_id, stable_giftbox_id)
        package = packages.setdefault(
            key,
            {
                "role_id": role_id,
                "window_key": window_key,
                "window_label": window_label,
                "giftbox_id": stable_giftbox_id,
                "giftbox_name": giftbox_name or "未命名礼包",
                "purchase_count": 0,
                "payment_amount": 0.0,
                "items": {},
                "payment_channel": "cash",
                "currency_name": "美元",
                "source_event": "role_pay",
            },
        )
        package["purchase_count"] = max(
            int(package["purchase_count"]),
            int(round(purchase_count)),
        )
        package["payment_amount"] = max(
            float(package["payment_amount"]),
            payment_amount,
        )
        if item_id or item_name:
            stable_item_id = item_id or f"name:{item_name}"
            items = package["items"]
            existing = items.get(stable_item_id)
            if existing is None:
                items[stable_item_id] = {
                    "item_id": item_id,
                    "item_name": item_name or "未命名道具",
                    "item_amount": item_amount,
                    "category": catalog.item_categories.get(item_id)
                    or classify_consumption_category(item_name),
                }
            else:
                existing["item_amount"] = max(float(existing["item_amount"]), item_amount)

    output: list[dict[str, object]] = []
    for package in packages.values():
        items = sorted(
            package.pop("items").values(),
            key=lambda item: (-float(item["item_amount"]), str(item["item_id"])),
        )
        # Demand direction follows the package proposition, not its incidental
        # contents. A generic package stays unclassified instead of allowing a
        # secondary material to override the player's apparent intent.
        category = classify_consumption_category(package["giftbox_name"])
        is_coin_acquisition = _is_dragon_coin_acquisition(
            str(package["giftbox_name"]),
            items,
        )
        output.append(
            {
                **package,
                "category": "龙币充值" if is_coin_acquisition else category,
                "is_demand_evidence": not is_coin_acquisition,
                "items_json": json.dumps(items[:12], ensure_ascii=False, separators=(",", ":")),
            }
        )
    output.sort(
        key=lambda item: (
            str(item["role_id"]),
            str(item["window_key"]),
            -float(item["payment_amount"]),
            str(item["giftbox_id"]),
        )
    )
    return output, window_label


def build_dragon_coin_package_rows(
    spend_rows: Sequence[dict[str, str]],
    reward_rows: Sequence[dict[str, str]],
    *,
    window_key: str,
    window_label: str,
    allowed_role_ids: set[str] | None = None,
    item_catalog: ItemCatalog | None = None,
) -> list[dict[str, object]]:
    """Link Dragon Coin spend to the uniquely matching paid reward at role+second."""
    catalog = item_catalog or ItemCatalog({}, {}, None)
    rewards_by_event: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in reward_rows:
        role_id = _clean_identifier(_detail_value(row, "role_id", "角色ID"))
        event_time = _clean_text(_detail_value(row, "#event_time", "event_time", "事件时间"))
        way_name = _clean_text(
            _detail_value(row, "way_id@way_name", "way_name", "途径名称")
        )
        if (
            not role_id
            or not event_time
            or "[付费]" not in way_name
            or _coerce_float(_detail_value(row, "var_num", "变化数量")) <= 0
            or (allowed_role_ids is not None and role_id not in allowed_role_ids)
        ):
            continue
        rewards_by_event[(role_id, event_time)].append(row)

    spend_by_event: dict[tuple[str, str], float] = defaultdict(float)
    for row in spend_rows:
        role_id = _clean_identifier(_detail_value(row, "role_id", "角色ID"))
        event_time = _clean_text(_detail_value(row, "#event_time", "event_time", "事件时间"))
        item_id = _clean_identifier(_detail_value(row, "item_id", "道具ID"))
        delta = _coerce_float(_detail_value(row, "var_num", "变化数量"))
        if (
            not role_id
            or not event_time
            or item_id != DRAGON_COIN_ITEM_ID
            or delta >= 0
            or (allowed_role_ids is not None and role_id not in allowed_role_ids)
        ):
            continue
        spend_by_event[(role_id, event_time)] += abs(delta)

    packages: dict[tuple[str, str], dict[str, Any]] = {}
    unmatched: dict[str, dict[str, Any]] = {}
    for event_key, spend_amount in spend_by_event.items():
        role_id, _ = event_key
        event_rewards = rewards_by_event.get(event_key, [])
        paid_ways = {
            _clean_text(_detail_value(row, "way_id@way_name", "way_name", "途径名称"))
            for row in event_rewards
            if _clean_text(
                _detail_value(row, "way_id@way_name", "way_name", "途径名称")
            )
        }
        if len(paid_ways) != 1:
            package = unmatched.setdefault(
                role_id,
                {
                    "role_id": role_id,
                    "window_key": window_key,
                    "window_label": window_label,
                    "giftbox_id": "dragon_coin:unmatched",
                    "giftbox_name": "用途未识别的龙币消费",
                    "category": "其他",
                    "purchase_count": 0,
                    "payment_amount": 0.0,
                    "payment_channel": "dragon_coin",
                    "currency_name": DRAGON_COIN_NAME,
                    "source_event": "Item",
                    "is_demand_evidence": False,
                    "items_json": "[]",
                },
            )
            package["purchase_count"] = int(package["purchase_count"]) + 1
            package["payment_amount"] = float(package["payment_amount"]) + spend_amount
            continue

        way_name = next(iter(paid_ways))
        first_reward = event_rewards[0]
        way_id = _clean_identifier(_detail_value(first_reward, "way_id", "途径ID"))
        package_id, package_name = _paid_package_identity(way_name, way_id)
        key = (role_id, package_id)
        package = packages.setdefault(
            key,
            {
                "role_id": role_id,
                "window_key": window_key,
                "window_label": window_label,
                "giftbox_id": f"dragon_coin:{package_id}",
                "giftbox_name": package_name,
                "purchase_count": 0,
                "payment_amount": 0.0,
                "items": {},
                "payment_channel": "dragon_coin",
                "currency_name": DRAGON_COIN_NAME,
                "source_event": "Item",
                "is_demand_evidence": True,
            },
        )
        package["purchase_count"] = int(package["purchase_count"]) + 1
        package["payment_amount"] = float(package["payment_amount"]) + spend_amount
        for reward in event_rewards:
            item_id = _clean_identifier(_detail_value(reward, "item_id", "道具ID"))
            item_name = _clean_text(
                _detail_value(
                    reward,
                    "item_id@item_name_2",
                    "item_name_2",
                    "item_name",
                    "道具名称",
                )
            ) or catalog.items.get(item_id, "")
            item_amount = max(
                _coerce_float(_detail_value(reward, "var_num", "变化数量")),
                0.0,
            )
            if not item_id and not item_name:
                continue
            stable_item_id = item_id or f"name:{item_name}"
            stored = package["items"].setdefault(
                stable_item_id,
                {
                    "item_id": item_id,
                    "item_name": item_name or "未命名道具",
                    "item_amount": 0.0,
                    "category": catalog.item_categories.get(item_id)
                    or classify_consumption_category(item_name),
                },
            )
            stored["item_amount"] = float(stored["item_amount"]) + item_amount

    output: list[dict[str, object]] = []
    for package in packages.values():
        items = sorted(
            package.pop("items").values(),
            key=lambda item: (-float(item["item_amount"]), str(item["item_id"])),
        )
        category = _package_category(str(package["giftbox_name"]), items)
        output.append(
            {
                **package,
                "category": category,
                "items_json": json.dumps(items[:12], ensure_ascii=False, separators=(",", ":")),
            }
        )
    output.extend(unmatched.values())
    output.sort(
        key=lambda item: (
            str(item["role_id"]),
            -int(bool(item.get("is_demand_evidence", True))),
            -float(item["payment_amount"]),
            str(item["giftbox_id"]),
        )
    )
    return output


def _item_absolute_time_range(
    *,
    window_key: str,
    as_of: date | None = None,
) -> tuple[dict[str, str], str]:
    end_date = (as_of or datetime.now().date()) - timedelta(days=1)
    if window_key == "lifetime":
        start_date = date(2023, 1, 1)
    else:
        window_days = {
            "recent_7d": 7,
            "recent_14d": 14,
            "recent_30d": 30,
        }.get(window_key)
        if window_days is None:
            raise ValueError(f"Unsupported purchase window: {window_key}")
        start_date = end_date - timedelta(days=window_days - 1)
    return (
        {
            "mode": "absolute",
            "start_time": f"{start_date.isoformat()} 00:00:00",
            "end_time": f"{end_date.isoformat()} 23:59:59",
        },
        f"{start_date.isoformat()}To{end_date.isoformat()}",
    )


def _filter_detail_rows_for_range(
    rows: Sequence[dict[str, str]],
    time_range: Mapping[str, str],
) -> list[dict[str, str]]:
    """Slice the already exported 30-day Item detail into shorter windows."""
    start_date = str(time_range.get("start_time") or "")[:10]
    end_date = str(time_range.get("end_time") or "")[:10]
    if not start_date or not end_date:
        return []
    output: list[dict[str, str]] = []
    for row in rows:
        event_date = _clean_text(
            _detail_value(row, "#event_time", "event_time", "事件时间")
        )[:10]
        if start_date <= event_date <= end_date:
            output.append(row)
    return output


def _detail_value(row: dict[str, str], *candidates: str) -> str:
    for candidate in candidates:
        if candidate in row:
            return str(row.get(candidate) or "")
    normalized_candidates = {_normalized_header(candidate) for candidate in candidates}
    for key, value in row.items():
        normalized_key = _normalized_header(key)
        if normalized_key in normalized_candidates or any(
            normalized_key.endswith(candidate) for candidate in normalized_candidates
        ):
            return str(value or "")
    return ""


def _normalized_header(value: object) -> str:
    return re.sub(r"[\s_.:\-/#]+", "", str(value or "").casefold())


def _paid_package_identity(way_name: str, way_id: str) -> tuple[str, str]:
    match = re.match(r"^\[付费\]\s*(\d+)?\s*(.*)$", way_name.strip())
    numeric_id = (match.group(1) if match else "") or way_id
    display_name = (match.group(2) if match else way_name).strip()
    package_id = numeric_id or f"way:{way_name}"
    return package_id, display_name or f"付费内容 {numeric_id or '待识别'}"


def _package_category(giftbox_name: str, items: Sequence[dict[str, Any]]) -> str:
    del items  # Contents remain drill-down evidence; they do not drive intent.
    return classify_consumption_category(giftbox_name)


def _normalize_dragon_coin_label(value: object) -> str:
    text = _clean_text(value)
    match = re.search(r"Dragon\s*Coin\s*[*×x]?\s*([\d,]+)?", text, flags=re.IGNORECASE)
    if not match:
        return text
    amount = str(match.group(1) or "").replace(",", "")
    return f"{DRAGON_COIN_NAME} × {amount}" if amount else DRAGON_COIN_NAME


def _is_dragon_coin_acquisition(
    giftbox_name: str,
    items: Sequence[dict[str, Any]],
) -> bool:
    normalized_name = giftbox_name.strip()
    if normalized_name == DRAGON_COIN_NAME or normalized_name.startswith(f"{DRAGON_COIN_NAME} ×"):
        return True
    return any(str(item.get("item_id") or "") == DRAGON_COIN_ITEM_ID for item in items)


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
        for field in (
            "role_name",
            "server_id",
            "server_name",
            "last_login_time",
            "cps_group",
            *PROFILE_POWER_FIELDS,
        )
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


def _coerce_optional_float(value: object) -> float | None:
    text = _clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


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
