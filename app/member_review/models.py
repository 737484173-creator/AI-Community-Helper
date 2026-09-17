from __future__ import annotations

from dataclasses import dataclass


REVIEW_STATUSES = (
    "可通过",
    "信息不完整",
    "区服ID异常",
    "需要人工审核",
    "已通过",
    "已拒绝",
)


@dataclass(frozen=True)
class ParsedMemberApplication:
    raw_text: str
    player_name: str | None
    server_id: str | None
    raw_server_input: str | None
    server_name: str | None
    discord_nickname: str | None
    status: str
    reason_code: str
    internal_reason: str
    confidence: float
    detected_server_ids: tuple[str, ...] = ()

