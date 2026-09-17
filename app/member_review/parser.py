from __future__ import annotations

import re

from app.member_review.models import ParsedMemberApplication
from app.member_review.nickname_formatter import generate_discord_nickname, get_server_name, normalize_server_id


SERVER_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?P<raw>[sS]?\s*\d{1,4})(?![A-Za-z0-9])")
LABEL_PATTERN = re.compile(
    r"\b(?:server\s*id|server|区服|区服id|角色名|角色名称|name|character\s*name|in-game\s*character\s*name)\b",
    re.IGNORECASE,
)


def _clean_player_name(text: str) -> str:
    cleaned = LABEL_PATTERN.sub(" ", text)
    cleaned = re.sub(r"[/\\\-:：,，|]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _remove_span(text: str, span: tuple[int, int]) -> str:
    return f"{text[:span[0]]} {text[span[1]:]}"


def parse_member_application(text: str, server_mapping: dict[str, str]) -> ParsedMemberApplication:
    raw_text = (text or "").strip()
    if not raw_text:
        return ParsedMemberApplication(
            raw_text=raw_text,
            player_name=None,
            server_id=None,
            raw_server_input=None,
            server_name=None,
            discord_nickname=None,
            status="信息不完整",
            reason_code="INCOMPLETE_APPLICATION",
            internal_reason="申请内容为空",
            confidence=0.0,
        )

    candidates = []
    for match in SERVER_PATTERN.finditer(raw_text):
        normalized = normalize_server_id(match.group("raw"))
        if normalized is None:
            continue
        candidates.append(
            {
                "raw": re.sub(r"\s+", "", match.group("raw")),
                "server_id": normalized,
                "span": match.span("raw"),
                "valid": normalized in server_mapping,
            }
        )

    valid_candidates = [candidate for candidate in candidates if candidate["valid"]]
    invalid_candidates = [candidate for candidate in candidates if not candidate["valid"]]

    if len(valid_candidates) > 1:
        return ParsedMemberApplication(
            raw_text=raw_text,
            player_name=None,
            server_id=None,
            raw_server_input=", ".join(candidate["raw"] for candidate in valid_candidates),
            server_name=None,
            discord_nickname=None,
            status="需要人工审核",
            reason_code="MULTIPLE_SERVER_IDS",
            internal_reason="检测到多个区服ID",
            confidence=0.3,
            detected_server_ids=tuple(candidate["server_id"] for candidate in valid_candidates),
        )

    if not valid_candidates and invalid_candidates:
        candidate = invalid_candidates[0]
        possible_name = _clean_player_name(_remove_span(raw_text, candidate["span"]))
        return ParsedMemberApplication(
            raw_text=raw_text,
            player_name=possible_name or None,
            server_id=candidate["server_id"],
            raw_server_input=candidate["raw"],
            server_name=None,
            discord_nickname=None,
            status="区服ID异常",
            reason_code="INVALID_SERVER_ID",
            internal_reason="区服ID不在合法服务器映射表中",
            confidence=0.4,
            detected_server_ids=tuple(candidate["server_id"] for candidate in invalid_candidates),
        )

    if not valid_candidates:
        name_candidate = _clean_player_name(raw_text)
        if name_candidate:
            return ParsedMemberApplication(
                raw_text=raw_text,
                player_name=name_candidate,
                server_id=None,
                raw_server_input=None,
                server_name=None,
                discord_nickname=None,
                status="信息不完整",
                reason_code="MISSING_SERVER_ID",
                internal_reason="缺少区服ID",
                confidence=0.25,
            )
        return ParsedMemberApplication(
            raw_text=raw_text,
            player_name=None,
            server_id=None,
            raw_server_input=None,
            server_name=None,
            discord_nickname=None,
            status="信息不完整",
            reason_code="INCOMPLETE_APPLICATION",
            internal_reason="无法识别完整申请信息",
            confidence=0.0,
        )

    candidate = valid_candidates[0]
    player_name = _clean_player_name(_remove_span(raw_text, candidate["span"]))
    server_name = get_server_name(candidate["server_id"], server_mapping)
    if not player_name:
        return ParsedMemberApplication(
            raw_text=raw_text,
            player_name=None,
            server_id=candidate["server_id"],
            raw_server_input=candidate["raw"],
            server_name=server_name,
            discord_nickname=None,
            status="信息不完整",
            reason_code="MISSING_PLAYER_NAME",
            internal_reason="缺少角色名称",
            confidence=0.45,
            detected_server_ids=(candidate["server_id"],),
        )

    nickname = generate_discord_nickname(candidate["server_id"], player_name, server_mapping)
    return ParsedMemberApplication(
        raw_text=raw_text,
        player_name=player_name,
        server_id=candidate["server_id"],
        raw_server_input=candidate["raw"],
        server_name=server_name,
        discord_nickname=nickname,
        status="可通过",
        reason_code="PASS",
        internal_reason="角色名称及区服ID均已识别",
        confidence=0.98,
        detected_server_ids=(candidate["server_id"],),
    )
