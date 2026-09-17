from __future__ import annotations

from datetime import datetime


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_datetime(value: datetime) -> str:
    return value.strftime(DATETIME_FORMAT)


def format_local_datetime(value: datetime) -> str:
    """Format an aware timestamp in the machine's local timezone.

    Discord timestamps are UTC-aware while report windows are local, naive
    timestamps.  Normalizing at ingestion keeps daily activity inside the
    expected local calendar day.
    """
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return format_datetime(value)


def parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, DATETIME_FORMAT)
