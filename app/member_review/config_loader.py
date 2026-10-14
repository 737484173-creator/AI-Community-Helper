from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.member_review.nickname_formatter import normalize_server_id
from config.settings import BASE_DIR


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


SERVER_OPEN_DATES_PATH = BASE_DIR / "app" / "vip" / "config" / "server_open_dates.json"
SERVER_MERGES_PATH = BASE_DIR / "app" / "vip" / "config" / "server_merges.json"
CHINA_TIMEZONE = timezone(timedelta(hours=8))


def current_server_date() -> date:
    """Use the operating region's calendar day for scheduled openings."""
    return datetime.now(CHINA_TIMEZONE).date()


def _server_open_schedule() -> tuple[set[str], dict[str, date]]:
    payload = _load_json(SERVER_OPEN_DATES_PATH, {})
    fully_unlocked = {str(value) for value in payload.get("fully_unlocked_servers", [])}
    open_dates = {
        str(server_id): date.fromisoformat(str(open_date))
        for server_id, open_date in payload.get("servers", {}).items()
    }
    return fully_unlocked, open_dates


def load_server_mapping(*, as_of: date | None = None) -> dict[str, str]:
    """Return opened source IDs, naming merged sources by their current primary."""
    data = _load_json(BASE_DIR / "config" / "server_mapping.json", {})
    fully_unlocked, open_dates = _server_open_schedule()
    reference = as_of or current_server_date()
    opened = {
        str(server_id): str(name)
        for server_id, name in data.items()
        if str(server_id) in fully_unlocked
        or (str(server_id) in open_dates and open_dates[str(server_id)] <= reference)
    }
    merge_config = _load_json(SERVER_MERGES_PATH, {})
    for group in merge_config.get("groups", []):
        effective_date = group.get("effective_date")
        primary = normalize_server_id(group.get("primary"))
        merge_active = (
            primary in opened
            and (not effective_date or date.fromisoformat(str(effective_date)) <= reference)
        )
        for member in group.get("members", []):
            source = normalize_server_id(member)
            if source in opened:
                opened[source] = opened[primary] if merge_active else f"S{source}"
    return opened


def load_planned_server_dates(*, as_of: date | None = None) -> dict[str, str]:
    """Return configured future servers for manual review before opening."""
    data = _load_json(BASE_DIR / "config" / "server_mapping.json", {})
    _, open_dates = _server_open_schedule()
    reference = as_of or current_server_date()
    return {
        str(server_id): open_dates[str(server_id)].isoformat()
        for server_id in data
        if str(server_id) in open_dates and open_dates[str(server_id)] > reference
    }


def load_review_messages() -> dict[str, str]:
    return dict(_load_json(BASE_DIR / "config" / "member_review_messages.json", {}))


def load_review_rules() -> dict[str, Any]:
    return dict(
        _load_json(
            BASE_DIR / "config" / "member_review_rules.json",
            {"mode": "manual_confirmation", "auto_approve_enabled": False},
        )
    )
