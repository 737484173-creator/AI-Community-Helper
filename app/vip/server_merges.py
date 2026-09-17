from __future__ import annotations

import json
import re
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


SERVER_MERGE_MAP = load_server_merge_map()


def canonical_server_id(value: Any) -> str:
    normalized = normalize_server_id(value)
    return SERVER_MERGE_MAP.get(normalized, normalized)


def server_merge_summary() -> str:
    grouped: dict[str, list[str]] = {}
    for source, primary in SERVER_MERGE_MAP.items():
        grouped.setdefault(primary, []).append(source)
    parts = []
    for primary, members in sorted(grouped.items(), key=lambda item: int(item[0])):
        ordered_members = sorted(members, key=int)
        parts.append(f"S{primary}（{' / '.join(f'S{member}' for member in ordered_members)}）")
    return "、".join(parts)


def apply_server_merges(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Canonicalize 区服 while preserving the source value for traceability."""
    if dataframe.empty or "区服" not in dataframe.columns:
        return dataframe.copy()
    output = dataframe.copy()
    source_zone = output["区服"].map(normalize_server_id)
    if "原区服" not in output.columns:
        output["原区服"] = source_zone
    else:
        output["原区服"] = output["原区服"].fillna(source_zone)
    output["区服"] = source_zone.map(lambda value: SERVER_MERGE_MAP.get(value, value))
    return output
