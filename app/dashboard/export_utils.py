from __future__ import annotations

import re

import pandas as pd


def records_to_csv(records: list[dict]) -> bytes:
    if not records:
        return b""
    return pd.DataFrame(records).to_csv(index=False).encode("utf-8-sig")


def text_to_markdown_bytes(content: str) -> bytes:
    return content.encode("utf-8")


def safe_download_filename(value: str, suffix: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_")
    if not normalized:
        normalized = "download"
    return f"{normalized}.{suffix.lstrip('.')}"
