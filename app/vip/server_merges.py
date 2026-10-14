from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


SERVER_MERGE_CONFIG_PATH = Path(__file__).parent / "config" / "server_merges.json"


def load_server_merge_map(path: str | Path = SERVER_MERGE_CONFIG_PATH) -> dict[str, str]:
    """Return source-server to current primary-server mappings."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for group in payload.get("groups", []):
        primary = normalize_server_id(group.get("primary"))
        if not primary:
            continue
        for member in group.get("members", []):
            source = normalize_server_id(member)
            if source:
                mapping[source] = primary
        mapping[primary] = primary
    return mapping


def normalize_server_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text == "/":
        return text
    match = re.fullmatch(r"[sS]?\s*(\d+)(?:\.0+)?", text)
    return str(int(match.group(1))) if match else text


def server_merge_config_revision() -> tuple[int, int]:
    stat = SERVER_MERGE_CONFIG_PATH.stat()
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=8)
def _cached_server_merge_map(_revision: tuple[int, int]) -> dict[str, str]:
    return load_server_merge_map()


def current_server_merge_map() -> dict[str, str]:
    return _cached_server_merge_map(server_merge_config_revision())


def canonical_server_id(value: Any) -> str:
    normalized = normalize_server_id(value)
    return current_server_merge_map().get(normalized, normalized)


def server_merge_summary() -> str:
    merge_map = current_server_merge_map()
    payload = json.loads(SERVER_MERGE_CONFIG_PATH.read_text(encoding="utf-8"))
    effective_dates = {
        normalize_server_id(group.get("primary")): str(group["effective_date"])
        for group in payload.get("groups", [])
        if group.get("effective_date")
    }
    grouped: dict[str, list[str]] = {}
    for source, primary in merge_map.items():
        grouped.setdefault(primary, []).append(source)
    parts = []
    for primary, members in sorted(grouped.items(), key=lambda item: int(item[0])):
        ordered_members = sorted(members, key=int)
        date_label = f"；{effective_dates[primary]} 生效" if primary in effective_dates else ""
        parts.append(f"S{primary}（{' / '.join(f'S{member}' for member in ordered_members)}{date_label}）")
    return "、".join(parts)


def apply_server_merges(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Canonicalize 区服 while preserving the source value for traceability."""
    if dataframe.empty or "区服" not in dataframe.columns:
        return dataframe.copy()
    output = dataframe.copy()
    merge_map = current_server_merge_map()
    source_zone = output["区服"].map(normalize_server_id)
    if "原区服" not in output.columns:
        output["原区服"] = source_zone
    else:
        output["原区服"] = output["原区服"].fillna(source_zone)
    output["区服"] = source_zone.map(lambda value: merge_map.get(value, value))
    return output
