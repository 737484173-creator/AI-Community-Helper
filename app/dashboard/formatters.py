from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time
from sqlite3 import Row
from typing import Any

from app.utils.time_utils import format_datetime


def rows_to_records(rows: Iterable[Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def truncate_text(value: str | None, max_length: int = 120) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def date_range_to_datetimes(start_date: date, end_date: date) -> tuple[str, str]:
    start = datetime.combine(start_date, time.min).replace(microsecond=0)
    end = datetime.combine(end_date, time.max).replace(microsecond=0)
    return format_datetime(start), format_datetime(end)
