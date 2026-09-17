from __future__ import annotations

from app.utils.constants import (
    MESSAGE_TYPE_BUG,
    MESSAGE_TYPE_COMPLAINT,
    MESSAGE_TYPE_EVENT_FEEDBACK,
    MESSAGE_TYPE_FAQ,
    MESSAGE_TYPE_OTHER,
    MESSAGE_TYPE_SUGGESTION,
)


BUG_TERMS = {"bug", "crash", "error", "stuck", "freeze", "broken", "cannot", "can't"}
SUGGESTION_TERMS = {
    "suggest",
    "suggestion",
    "should",
    "could",
    "hope",
    "please add",
    "add",
    "improve",
}
EVENT_TERMS = {"event", "poll", "survey", "quiz", "activity"}
COMPLAINT_TERMS = {
    "angry",
    "bad",
    "unfair",
    "complaint",
    "refund",
    "scam",
    "terrible",
    "too low",
    "too hard",
    "missing",
}
FAQ_TERMS = {"how", "what", "why", "where", "when", "help", "support", "login", "payment"}


def classify_message(message: str) -> str:
    normalized = message.lower()
    if _contains_any(normalized, COMPLAINT_TERMS):
        return MESSAGE_TYPE_COMPLAINT
    if _contains_any(normalized, BUG_TERMS):
        return MESSAGE_TYPE_BUG
    if _contains_any(normalized, SUGGESTION_TERMS):
        return MESSAGE_TYPE_SUGGESTION
    if _contains_any(normalized, EVENT_TERMS):
        return MESSAGE_TYPE_EVENT_FEEDBACK
    if "?" in normalized or _contains_any(normalized, FAQ_TERMS):
        return MESSAGE_TYPE_FAQ
    return MESSAGE_TYPE_OTHER


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)
