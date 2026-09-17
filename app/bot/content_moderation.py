from __future__ import annotations

import re
from dataclasses import dataclass


MONITORED_CHANNEL_NAMES = {
    "ask_for_help",
    "game-chat",
    "suggestion-discussion",
}

PROFANITY_PATTERNS = (
    r"\bf+u+c+k+(?:ing|ed|er|s)?\b",
    r"\bs+h+i+t+(?:ty)?\b",
    r"\bbull\s*shit\b",
    r"\bwtf\b",
    r"\bstfu\b",
    r"\bdamn\b",
    r"\basshole\b",
    r"\bbastard\b",
    r"\bidiot\b",
    r"\bmoron\b",
    r"\bstupid\b",
)

HEATED_PATTERNS = (
    r"\bwhat the hell\b",
    r"\btrash\b",
    r"\bgarbage\b",
    r"\bscam\b",
    r"\bworst\b",
    r"\bbroken\b",
    r"\bshut (?:this|it|the bot|bot)\b",
    r"\bfix (?:this|your|the)\b",
)

ANGER_TERMS = {
    "angry",
    "mad",
    "broken",
    "scam",
    "trash",
    "garbage",
    "worst",
    "fix",
    "hell",
    "wtf",
}


@dataclass(frozen=True)
class ModerationResult:
    should_capture: bool
    reason: str | None = None


def is_monitored_channel(channel_name: str | None) -> bool:
    return normalize_monitored_channel_name(channel_name) in MONITORED_CHANNEL_NAMES


def normalize_monitored_channel_name(channel_name: str | None) -> str:
    if not channel_name:
        return ""
    normalized = channel_name.strip().lower()
    if "│" in normalized:
        normalized = normalized.rsplit("│", maxsplit=1)[-1]
    if "|" in normalized:
        normalized = normalized.rsplit("|", maxsplit=1)[-1]
    return normalized.strip()


def analyze_public_message(content: str) -> ModerationResult:
    normalized = " ".join(content.strip().lower().split())
    if not normalized:
        return ModerationResult(False)

    if _matches_any(normalized, PROFANITY_PATTERNS):
        return ModerationResult(True, "脏字/攻击性用语")

    if _matches_any(normalized, HEATED_PATTERNS):
        return ModerationResult(True, "强烈负面表达")

    if _looks_shouted(content) and _contains_anger_term(normalized):
        return ModerationResult(True, "高强度情绪表达")

    return ModerationResult(False)


def public_message_risk_level(content: str, reason: str | None = None) -> str | None:
    """Return the dashboard risk level for a captured public message."""
    moderation = analyze_public_message(content)
    if not moderation.should_capture:
        return None

    combined = f"{reason or moderation.reason or ''} {content}".lower()
    if any(
        token in combined
        for token in ("脏字", "攻击", "fuck", "stfu", "asshole", "bastard")
    ):
        return "高风险"
    if any(
        token in combined
        for token in ("高强度", "wtf", "!!!", "scam", "worst", "trash", "garbage")
    ):
        return "中风险"
    return "低风险"


def public_message_risk_type(reason: str | None) -> str:
    """Return the shared dashboard category for a moderation reason."""
    text = str(reason or "")
    if "脏字" in text or "攻击" in text:
        return "脏字/攻击"
    if "负面" in text:
        return "强烈负面"
    if "高强度" in text or "情绪" in text:
        return "高强度情绪"
    return "风险表达"


def should_capture_public_message(content: str, channel_name: str | None) -> bool:
    return is_monitored_channel(channel_name) and analyze_public_message(content).should_capture


def _matches_any(content: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, content, flags=re.IGNORECASE) for pattern in patterns)


def _contains_anger_term(content: str) -> bool:
    words = set(re.findall(r"[a-zA-Z']+", content.lower()))
    return bool(words & ANGER_TERMS)


def _looks_shouted(content: str) -> bool:
    letters = [char for char in content if char.isalpha()]
    uppercase = [char for char in letters if char.isupper()]
    exclamation_count = content.count("!")
    return (
        len(letters) >= 8
        and len(uppercase) / max(len(letters), 1) >= 0.55
    ) or exclamation_count >= 3
