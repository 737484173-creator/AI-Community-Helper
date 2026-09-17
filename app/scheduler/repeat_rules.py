from __future__ import annotations

from datetime import datetime, timedelta


WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def calculate_next_publish_time(
    publish_time: datetime,
    repeat_rule: str,
) -> datetime | None:
    normalized = repeat_rule.strip().lower()
    if normalized in {"", "none"}:
        return None
    if normalized == "daily":
        return publish_time + timedelta(days=1)
    if normalized.startswith("weekly:"):
        return _next_weekly_time(publish_time, normalized)
    raise ValueError(f"Unsupported repeat_rule: {repeat_rule}")


def _next_weekly_time(publish_time: datetime, repeat_rule: str) -> datetime:
    parts = repeat_rule.split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid weekly repeat_rule: {repeat_rule}")

    _, weekday_name, hour_text, minute_text = parts
    if weekday_name not in WEEKDAY_INDEX:
        raise ValueError(f"Invalid weekday in repeat_rule: {repeat_rule}")

    hour = int(hour_text)
    minute = int(minute_text)
    target_weekday = WEEKDAY_INDEX[weekday_name]
    days_ahead = (target_weekday - publish_time.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7

    next_date = publish_time + timedelta(days=days_ahead)
    return next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

