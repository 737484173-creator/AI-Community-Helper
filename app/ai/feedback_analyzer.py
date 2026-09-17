from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.constants import (
    FEEDBACK_CATEGORY_BALANCE_ISSUE,
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_CATEGORY_EVENT_SUGGESTION,
    FEEDBACK_CATEGORY_GAMEPLAY_SUGGESTION,
    FEEDBACK_CATEGORY_OTHER,
    FEEDBACK_CATEGORY_REWARD_ISSUE,
    MESSAGE_TYPE_BUG,
    MESSAGE_TYPE_COMPLAINT,
    MESSAGE_TYPE_EVENT_FEEDBACK,
    MESSAGE_TYPE_SUGGESTION,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    SENTIMENT_NEGATIVE,
    SENTIMENT_NEUTRAL,
    SENTIMENT_POSITIVE,
)


TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)

BUG_TERMS = {"bug", "crash", "error", "stuck", "freeze", "broken", "login", "loading"}
REWARD_TERMS = {"reward", "rewards", "drop", "drops", "chest", "gem", "coin", "loot"}
BALANCE_TERMS = {"balance", "op", "overpowered", "weak", "nerf", "buff", "unfair"}
EVENT_TERMS = {"event", "activity", "poll", "survey", "quiz"}
GAMEPLAY_TERMS = {"gameplay", "mode", "level", "quest", "match", "battle", "feature"}

HIGH_PRIORITY_TERMS = {"crash", "cannot", "can't", "broken", "lost", "refund", "payment"}
MEDIUM_PRIORITY_TERMS = {"stuck", "error", "failed", "missing", "unfair"}

NEGATIVE_TERMS = {
    "bad",
    "angry",
    "hate",
    "terrible",
    "unfair",
    "broken",
    "failed",
    "missing",
    "crash",
    "crashes",
    "cannot",
    "can't",
}
POSITIVE_TERMS = {"good", "great", "love", "like", "awesome", "nice", "fun"}


@dataclass(frozen=True)
class FeedbackAnalysis:
    category: str
    feature: str | None
    keywords: list[str]
    sentiment: str
    priority: str


class FeedbackAnalyzer:
    def analyze(self, content: str, message_type: str) -> FeedbackAnalysis | None:
        if message_type not in {
            MESSAGE_TYPE_BUG,
            MESSAGE_TYPE_SUGGESTION,
            MESSAGE_TYPE_EVENT_FEEDBACK,
            MESSAGE_TYPE_COMPLAINT,
        }:
            return None

        normalized = content.lower()
        category = _detect_category(normalized, message_type)
        return FeedbackAnalysis(
            category=category,
            feature=_detect_feature(normalized, category),
            keywords=_extract_keywords(normalized),
            sentiment=_detect_sentiment(normalized),
            priority=_detect_priority(normalized, category, message_type),
        )


def _detect_category(content: str, message_type: str) -> str:
    if message_type == MESSAGE_TYPE_BUG or _contains_any(content, BUG_TERMS):
        return FEEDBACK_CATEGORY_BUG
    if _contains_any(content, REWARD_TERMS):
        return FEEDBACK_CATEGORY_REWARD_ISSUE
    if _contains_any(content, BALANCE_TERMS):
        return FEEDBACK_CATEGORY_BALANCE_ISSUE
    if message_type == MESSAGE_TYPE_EVENT_FEEDBACK or _contains_any(content, EVENT_TERMS):
        return FEEDBACK_CATEGORY_EVENT_SUGGESTION
    if message_type == MESSAGE_TYPE_SUGGESTION or _contains_any(content, GAMEPLAY_TERMS):
        return FEEDBACK_CATEGORY_GAMEPLAY_SUGGESTION
    if message_type == MESSAGE_TYPE_COMPLAINT:
        return FEEDBACK_CATEGORY_OTHER
    return FEEDBACK_CATEGORY_OTHER


def _detect_feature(content: str, category: str) -> str | None:
    if "login" in content or "loading" in content:
        return "Login"
    if "payment" in content or "refund" in content:
        return "Payment"
    if category == FEEDBACK_CATEGORY_REWARD_ISSUE:
        return "Reward"
    if category == FEEDBACK_CATEGORY_BALANCE_ISSUE:
        return "Balance"
    if category == FEEDBACK_CATEGORY_EVENT_SUGGESTION:
        return "Event"
    if category == FEEDBACK_CATEGORY_GAMEPLAY_SUGGESTION:
        return "Gameplay"
    return None


def _detect_sentiment(content: str) -> str:
    negative_hits = sum(1 for term in NEGATIVE_TERMS if term in content)
    positive_hits = sum(1 for term in POSITIVE_TERMS if term in content)
    if negative_hits > positive_hits:
        return SENTIMENT_NEGATIVE
    if positive_hits > negative_hits:
        return SENTIMENT_POSITIVE
    return SENTIMENT_NEUTRAL


def _detect_priority(content: str, category: str, message_type: str) -> str:
    if _contains_any(content, HIGH_PRIORITY_TERMS):
        return PRIORITY_HIGH
    if category == FEEDBACK_CATEGORY_BUG and _contains_any(content, MEDIUM_PRIORITY_TERMS):
        return PRIORITY_MEDIUM
    if message_type == MESSAGE_TYPE_COMPLAINT:
        return PRIORITY_MEDIUM
    if _contains_any(content, MEDIUM_PRIORITY_TERMS):
        return PRIORITY_MEDIUM
    return PRIORITY_LOW


def _extract_keywords(content: str, max_keywords: int = 8) -> list[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "when",
        "please",
        "game",
    }
    seen: set[str] = set()
    keywords: list[str] = []
    for token in TOKEN_PATTERN.findall(content):
        if token in stop_words or token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= max_keywords:
            break
    return keywords


def _contains_any(content: str, terms: set[str]) -> bool:
    return any(term in content for term in terms)
