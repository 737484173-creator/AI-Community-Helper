from __future__ import annotations

from app.member_review.config_loader import load_review_messages


DEFAULT_REJECTION_REASON = (
    "We couldn't clearly identify your character and server information. "
    "Please resubmit your application using a clear format such as: S14 Bubble."
)


def generate_rejection_reason(reason_code: str) -> str:
    return load_review_messages().get(reason_code, DEFAULT_REJECTION_REASON)
