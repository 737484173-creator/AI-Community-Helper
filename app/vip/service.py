from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd

from app.database.repositories.vip_ae_repository import AEVIPSnapshotRepository
from app.vip.ae_sync import DEFAULT_AE_PROJECT_ID
from app.vip.scoring.router import score_dataframe
from app.vip.server_merges import apply_server_merges
from app.vip.utils.excel_reader import ExcelReadReport, REQUIRED_FIELDS, _infer_server_type, read_vip_excel


CONTACT_PRIORITIES = ("立即触达", "优先触达")
HIDDEN_DETAIL_COLUMNS = ("DC是否建联", "近一个月充值")
REQUIRED_PAGE_COLUMNS = ("玩家分组", "区服", "用户来源", "价值分", "风险分", "触达优先级", "原因")
DEFAULT_VIP_FILE = Path("data") / "vip" / "VIP建联表格（7.05）.xlsx"
RETIREMENT_INACTIVITY_DAYS = 30


@dataclass(frozen=True)
class VIPWorkbook:
    raw_df: pd.DataFrame
    scored_df: pd.DataFrame
    active_df: pd.DataFrame
    report: ExcelReadReport
    retired_count: int
    abnormal_count: int
    missing_page_columns: list[str]
    as_of: datetime | None = None


def load_vip_workbook(source: Path | BytesIO) -> VIPWorkbook:
    raw_df, report = read_vip_excel(source)
    return build_vip_workbook(raw_df, report)


def load_ae_vip_workbook(
    db_path: str | Path | None,
    project_id: int = DEFAULT_AE_PROJECT_ID,
) -> VIPWorkbook | None:
    rows = AEVIPSnapshotRepository(db_path).list_snapshot(project_id)
    if not rows:
        return None
    snapshot_as_of = _latest_snapshot_datetime(rows)
    raw_df = pd.DataFrame(
        [
            {
                "来源Sheet": f"AE项目{project_id}",
                "角色ID": row["role_id"],
                "区服": row["server_id"] or row["server_name"] or "",
                "角色名": row["role_name"] or "",
                "最后登录时间": row["last_login_time"],
                "累计充值": row["total_payment_amount"],
                "近一周充值": row["payment_7d_amount"],
                "前7日充值": row["payment_previous_7d_amount"],
                "过去28日周均充值": row["payment_28d_weekly_avg"],
                "服务器类型": _infer_server_type(row["server_id"] or row["server_name"] or "") or row["server_type"],
                "用户来源": row["user_source"],
            }
            for row in rows
        ]
    )
    raw_df["最后登录时间"] = pd.to_datetime(raw_df["最后登录时间"], errors="coerce")
    report = ExcelReadReport(
        sheet_names=[f"AE项目{project_id}"],
        matched_columns={field: field for field in REQUIRED_FIELDS},
        missing_fields=[],
    )
    return build_vip_workbook(raw_df, report, as_of=snapshot_as_of)


def build_vip_workbook(
    raw_df: pd.DataFrame,
    report: ExcelReadReport,
    *,
    as_of: datetime | None = None,
) -> VIPWorkbook:
    effective_as_of = as_of or datetime.now()
    raw_df = apply_server_merges(raw_df)
    if "服务器类型" in raw_df.columns:
        inferred_server_type = raw_df["区服"].map(_infer_server_type)
        raw_df["服务器类型"] = inferred_server_type.where(
            inferred_server_type.ne(""), raw_df["服务器类型"]
        )
    scored_df = score_dataframe(raw_df, as_of=effective_as_of)
    scored_df, missing_page_columns = ensure_page_columns(scored_df)
    scored_df = mark_retired_players(scored_df, as_of=effective_as_of)
    retired = is_retired_player(scored_df, as_of=effective_as_of)
    active_df = scored_df[~retired].copy()
    abnormal_count = int(((scored_df["玩家分组"] == "未分类") & ~retired).sum())
    return VIPWorkbook(
        raw_df=raw_df,
        scored_df=scored_df,
        active_df=active_df,
        report=report,
        retired_count=int(is_retired_player(scored_df).sum()),
        abnormal_count=abnormal_count,
        missing_page_columns=missing_page_columns,
        as_of=effective_as_of,
    )


def ensure_page_columns(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    output = dataframe.copy()
    missing_columns = [column for column in REQUIRED_PAGE_COLUMNS if column not in output.columns]
    for column in missing_columns:
        output[column] = 0 if column.endswith("分") else ""
    return output, missing_columns


def is_retired_player(
    dataframe: pd.DataFrame,
    as_of: datetime | date | None = None,
) -> pd.Series:
    retired = pd.Series(False, index=dataframe.index, dtype=bool)
    if "玩家分组" in dataframe.columns:
        retired |= dataframe["玩家分组"].astype(str).str.strip().eq("已退游")
    if "区服" in dataframe.columns:
        retired |= dataframe["区服"].astype(str).str.strip().eq("/")
    retired |= _inactive_player_mask(dataframe, as_of=as_of)
    return retired


def mark_retired_players(
    dataframe: pd.DataFrame,
    as_of: datetime | date | None = None,
) -> pd.DataFrame:
    output = dataframe.copy()
    zone_retired = (
        output["区服"].astype(str).str.strip().eq("/")
        if "区服" in output.columns
        else pd.Series(False, index=output.index, dtype=bool)
    )
    inactive_retired = _inactive_player_mask(output, as_of=as_of)
    retired = zone_retired | inactive_retired
    if retired.any():
        output.loc[retired, "玩家分组"] = "已退游"
        output.loc[retired, "触达优先级"] = "暂不触达"
        output.loc[zone_retired, "原因"] = "区服为 /，已退游，不纳入运营统计"
        output.loc[inactive_retired & ~zone_retired, "原因"] = (
            f"最后登录距数据基准日达到 {RETIREMENT_INACTIVITY_DAYS} 天，已退游，不纳入运营统计"
        )
    return output


def _inactive_player_mask(
    dataframe: pd.DataFrame,
    *,
    as_of: datetime | date | None,
) -> pd.Series:
    if "最后登录时间" not in dataframe.columns:
        return pd.Series(False, index=dataframe.index, dtype=bool)
    reference_day = _calendar_date(as_of or datetime.now())
    cutoff_day = reference_day - timedelta(days=RETIREMENT_INACTIVITY_DAYS)
    login_days = dataframe["最后登录时间"].map(_calendar_date_or_none)
    return login_days.map(lambda login_day: login_day is not None and login_day <= cutoff_day).astype(bool)


def _calendar_date(value: datetime | date) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value.date()
    return value


def _calendar_date_or_none(value: object) -> date | None:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(None)
    return parsed.date()


def _latest_snapshot_datetime(rows: list[object]) -> datetime:
    sync_values = [str(row["synced_at"]) for row in rows if row["synced_at"]]
    if not sync_values:
        return datetime.now()
    latest_value = max(sync_values)
    try:
        parsed = datetime.fromisoformat(latest_value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def filter_options(dataframe: pd.DataFrame, column: str) -> list[str]:
    if column not in dataframe.columns:
        return []
    return sorted(dataframe[column].dropna().astype(str).unique().tolist())


def vip_summary_metrics(workbook: VIPWorkbook) -> dict[str, int]:
    active_df = workbook.active_df
    return {
        "总玩家": int(len(workbook.scored_df)),
        "有效玩家": int(len(active_df)),
        "退游玩家": workbook.retired_count,
        "待触达": int(active_df["触达优先级"].isin(CONTACT_PRIORITIES).sum()),
        "未分类": workbook.abnormal_count,
    }


def contact_count_for_group(dataframe: pd.DataFrame, group_name: str) -> int:
    return int(
        (
            dataframe["玩家分组"].eq(group_name)
            & dataframe["触达优先级"].isin(CONTACT_PRIORITIES)
        ).sum()
    )


def group_metrics(dataframe: pd.DataFrame) -> pd.DataFrame:
    grouped = dataframe[dataframe["玩家分组"] != "未分类"].copy()
    if grouped.empty:
        return pd.DataFrame(columns=["玩家分组", "平均价值分", "平均风险分", "待触达人数"])
    return (
        grouped.groupby("玩家分组", as_index=False)
        .agg(
            平均价值分=("价值分", "mean"),
            平均风险分=("风险分", "mean"),
            待触达人数=("触达优先级", lambda values: int(values.isin(CONTACT_PRIORITIES).sum())),
        )
        .round(2)
    )


def server_contact_counts(dataframe: pd.DataFrame) -> pd.DataFrame:
    return (
        dataframe[dataframe["触达优先级"].isin(CONTACT_PRIORITIES)]
        .groupby("区服", dropna=False)
        .size()
        .reset_index(name="待触达人数")
        .sort_values("待触达人数", ascending=False)
    )


def dataframe_to_excel_bytes(dataframe: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="玩家评分明细")
    return output.getvalue()
