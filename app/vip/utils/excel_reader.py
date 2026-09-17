from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from app.vip.server_merges import apply_server_merges, canonical_server_id


REQUIRED_FIELDS = ["角色ID", "区服", "角色名", "最后登录时间", "累计充值", "近一周充值", "服务器类型", "用户来源"]
OPTIONAL_ANALYSIS_FIELDS = ["前7日充值", "过去28日周均充值"]
NORMALIZED_FIELDS = [*REQUIRED_FIELDS, *OPTIONAL_ANALYSIS_FIELDS]
OLD_SERVER_IDS = frozenset(str(server_id) for server_id in range(1, 21))

FIELD_ALIASES = {
    "角色ID": ["角色ID", "角色id", "角色 Id", "role_id", "role id", "uid", "玩家ID", "玩家id"],
    "区服": ["区服", "当前区服名称", "当前区服", "服务器", "server", "server_id", "区服名称"],
    "角色名": ["角色名", "昵称", "玩家昵称", "玩家名", "role_name", "role name", "name"],
    "最后登录时间": ["最后登录时间", "最后登录", "最近登录时间", "last_login", "last login"],
    "累计充值": ["累计充值", "累计充值金额", "总充值", "总充值金额", "total_recharge", "lifetime_spend"],
    "近一周充值": ["近一周充值", "近一周充值金额", "7日充值", "七日充值", "weekly_recharge", "last_7d_spend"],
    "前7日充值": ["前7日充值", "前一周充值", "8至14日充值", "previous_7d_spend", "prior_7d_spend"],
    "过去28日周均充值": ["过去28日周均充值", "前28日周均充值", "28日周均充值", "rolling_28d_weekly_avg"],
    "服务器类型": ["服务器类型", "服类型", "server_type", "server type"],
    "用户来源": ["用户来源", "来源", "渠道来源", "user_source", "user source", "source"],
}


@dataclass(frozen=True)
class ExcelReadReport:
    sheet_names: list[str]
    matched_columns: dict[str, str | None]
    missing_fields: list[str]


def read_vip_excel(file: str | Path | BinaryIO) -> tuple[pd.DataFrame, ExcelReadReport]:
    """Read a VIP .xlsx workbook and return normalized VIP fields as a DataFrame."""
    _validate_xlsx(file)

    excel_file = pd.ExcelFile(file, engine="openpyxl")
    frames: list[pd.DataFrame] = []
    matched_columns: dict[str, str | None] = {field: None for field in NORMALIZED_FIELDS}

    for sheet_name in excel_file.sheet_names:
        raw_df = pd.read_excel(excel_file, sheet_name=sheet_name, engine="openpyxl")
        raw_df = _drop_empty_rows_and_columns(raw_df)
        if raw_df.empty:
            continue

        column_map = detect_vip_columns(raw_df)
        for field, column in column_map.items():
            if column and matched_columns[field] is None:
                matched_columns[field] = column

        normalized = _normalize_dataframe(raw_df, column_map)
        if not normalized.empty:
            normalized.insert(0, "来源Sheet", sheet_name)
            frames.append(normalized)

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["来源Sheet", *NORMALIZED_FIELDS])
    result = _clean_result(result)
    missing_fields = [field for field in REQUIRED_FIELDS if field not in result.columns or result[field].isna().all()]

    return result, ExcelReadReport(
        sheet_names=excel_file.sheet_names,
        matched_columns=matched_columns,
        missing_fields=missing_fields,
    )


def detect_vip_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Detect required VIP columns from source Excel headers."""
    source_columns = [str(column).strip() for column in df.columns]
    normalized_lookup = {_normalize_name(column): column for column in source_columns}
    detected: dict[str, str | None] = {}

    for field, aliases in FIELD_ALIASES.items():
        detected[field] = _find_column(
            aliases,
            normalized_lookup,
            allow_fuzzy=field in REQUIRED_FIELDS,
        )

    return detected


def _validate_xlsx(file: str | Path | BinaryIO) -> None:
    if hasattr(file, "name"):
        file_name = str(getattr(file, "name"))
    else:
        file_name = str(file)

    if not file_name.lower().endswith(".xlsx"):
        raise ValueError("仅支持 .xlsx 文件")


def _drop_empty_rows_and_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(axis=0, how="all").dropna(axis=1, how="all")


def _normalize_dataframe(df: pd.DataFrame, column_map: dict[str, str | None]) -> pd.DataFrame:
    output = pd.DataFrame()
    for field in NORMALIZED_FIELDS:
        source_column = column_map.get(field)
        output[field] = df[source_column] if source_column in df.columns else pd.NA

    output = output.dropna(subset=["角色ID", "角色名"], how="all")
    return output


def _clean_result(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    cleaned = df.copy()
    cleaned["角色ID"] = cleaned["角色ID"].astype("string").str.replace(r"\.0$", "", regex=True).str.strip()
    cleaned["区服"] = cleaned["区服"].astype("string").str.strip()
    cleaned["角色名"] = cleaned["角色名"].astype("string").str.strip()
    cleaned["最后登录时间"] = pd.to_datetime(cleaned["最后登录时间"], errors="coerce")
    cleaned["累计充值"] = pd.to_numeric(cleaned["累计充值"], errors="coerce").fillna(0)
    cleaned["近一周充值"] = pd.to_numeric(cleaned["近一周充值"], errors="coerce").fillna(0)
    cleaned["前7日充值"] = pd.to_numeric(cleaned["前7日充值"], errors="coerce")
    cleaned["过去28日周均充值"] = pd.to_numeric(cleaned["过去28日周均充值"], errors="coerce")
    cleaned = apply_server_merges(cleaned)
    cleaned["服务器类型"] = cleaned.apply(_fill_server_type_from_zone, axis=1)
    cleaned["用户来源"] = cleaned["用户来源"].astype("string").str.strip()
    cleaned["用户来源"] = cleaned.apply(_fill_user_source_from_sheet, axis=1)
    cleaned = cleaned[cleaned["角色ID"].notna() & (cleaned["角色ID"] != "")]
    return cleaned.reset_index(drop=True)


def _fill_server_type_from_zone(row: pd.Series) -> str:
    inferred_server_type = _infer_server_type(row.get("区服"))
    if inferred_server_type:
        return inferred_server_type
    server_type = row.get("服务器类型")
    if pd.notna(server_type) and str(server_type).strip():
        return str(server_type).strip()
    return ""


def _infer_server_type(zone: object) -> str:
    if pd.isna(zone):
        return ""
    zone_text = canonical_server_id(zone)
    if not zone_text or zone_text == "/":
        return ""
    if not zone_text.isdigit():
        return ""
    if zone_text in OLD_SERVER_IDS:
        return "老服"
    return "新服"


def _fill_user_source_from_sheet(row: pd.Series) -> str:
    user_source = row.get("用户来源")
    if pd.notna(user_source) and str(user_source).strip():
        return str(user_source).strip()
    return _infer_user_source(row.get("来源Sheet"))


def _infer_user_source(sheet_name: object) -> str:
    sheet_text = str(sheet_name).strip().lower()
    if sheet_text == "sheet2":
        return "自然量"
    if sheet_text == "sheet3":
        return "CPS"
    return ""


def _find_column(
    aliases: list[str],
    normalized_lookup: dict[str, str],
    *,
    allow_fuzzy: bool = True,
) -> str | None:
    for alias in aliases:
        normalized_alias = _normalize_name(alias)
        if normalized_alias in normalized_lookup:
            return normalized_lookup[normalized_alias]

    if not allow_fuzzy:
        return None

    possible_matches = get_close_matches(
        _normalize_name(aliases[0]),
        normalized_lookup.keys(),
        n=1,
        cutoff=0.72,
    )
    if possible_matches:
        return normalized_lookup[possible_matches[0]]

    return None


def _normalize_name(value: object) -> str:
    return str(value).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
