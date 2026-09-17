from __future__ import annotations

from app.ai.feedback_analyzer import FeedbackAnalyzer
from app.utils.constants import (
    FEEDBACK_CATEGORY_BALANCE_ISSUE,
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_CATEGORY_GAMEPLAY_SUGGESTION,
    FEEDBACK_CATEGORY_REWARD_ISSUE,
    MESSAGE_TYPE_BUG,
    MESSAGE_TYPE_COMPLAINT,
    MESSAGE_TYPE_SUGGESTION,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    SENTIMENT_NEGATIVE,
    SENTIMENT_NEUTRAL,
)


def test_feedback_analyzer_detects_high_priority_login_bug() -> None:
    result = FeedbackAnalyzer().analyze(
        "The game crashes when I login and I cannot enter.",
        MESSAGE_TYPE_BUG,
    )

    assert result is not None
    assert result.category == FEEDBACK_CATEGORY_BUG
    assert result.feature == "Login"
    assert result.sentiment == SENTIMENT_NEGATIVE
    assert result.priority == PRIORITY_HIGH
    assert "crashes" in result.keywords


def test_feedback_analyzer_detects_reward_complaint() -> None:
    result = FeedbackAnalyzer().analyze(
        "The dragon mine reward is too low and feels bad.",
        MESSAGE_TYPE_COMPLAINT,
    )

    assert result is not None
    assert result.category == FEEDBACK_CATEGORY_REWARD_ISSUE
    assert result.feature == "Reward"
    assert result.sentiment == SENTIMENT_NEGATIVE
    assert result.priority == PRIORITY_MEDIUM


def test_feedback_analyzer_detects_gameplay_suggestion() -> None:
    result = FeedbackAnalyzer().analyze(
        "Please add a new guild battle mode.",
        MESSAGE_TYPE_SUGGESTION,
    )

    assert result is not None
    assert result.category == FEEDBACK_CATEGORY_GAMEPLAY_SUGGESTION
    assert result.feature == "Gameplay"
    assert result.sentiment == SENTIMENT_NEUTRAL
    assert result.priority == PRIORITY_LOW


def test_feedback_analyzer_detects_balance_issue() -> None:
    result = FeedbackAnalyzer().analyze(
        "This hero is overpowered and unfair.",
        MESSAGE_TYPE_COMPLAINT,
    )

    assert result is not None
    assert result.category == FEEDBACK_CATEGORY_BALANCE_ISSUE

