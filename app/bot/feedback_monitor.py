from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re

from app.ai.feedback_analyzer import FeedbackAnalyzer
from app.ai.message_classifier import classify_message
from app.database.repositories.feedback_repository import FeedbackRepository
from app.utils.constants import (
    MESSAGE_TYPE_BUG,
    MESSAGE_TYPE_SUGGESTION,
)


MONITORED_FEEDBACK_CHANNELS = (
    "bug-report",
    "feedback_wanted",
    "game-suggestions",
)
EXCLUDED_FEEDBACK_USER_IDS = ("1340955757465698354",)

CHANNEL_DEFAULT_MESSAGE_TYPES = {
    "bug-report": MESSAGE_TYPE_BUG,
    "feedback_wanted": MESSAGE_TYPE_SUGGESTION,
    "game-suggestions": MESSAGE_TYPE_SUGGESTION,
}
DUPLICATE_SIMILARITY_THRESHOLD = 0.9


@dataclass(frozen=True)
class FeedbackCaptureResult:
    captured: bool
    feedback_id: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FeedbackSource:
    channel_id: str
    channel_name: str | None
    thread_title: str | None


def feedback_source_from_channel(channel) -> FeedbackSource:
    """Describe where a public feedback message can be answered."""
    parent_channel = getattr(channel, "parent", None)
    parent_channel_name = getattr(parent_channel, "name", None)
    return FeedbackSource(
        channel_id=str(channel.id),
        channel_name=parent_channel_name or getattr(channel, "name", None),
        thread_title=(
            getattr(channel, "name", None)
            if parent_channel_name
            else None
        ),
    )


class PublicFeedbackMonitor:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.feedback = FeedbackRepository(db_path)
        self.analyzer = FeedbackAnalyzer()

    def capture_if_needed(
        self,
        *,
        discord_user_id: str,
        discord_user_name: str | None = None,
        channel_id: str,
        channel_name: str | None,
        thread_title: str | None = None,
        content: str,
    ) -> FeedbackCaptureResult:
        normalized_channel = normalize_feedback_channel_name(channel_name)
        if normalized_channel not in MONITORED_FEEDBACK_CHANNELS:
            return FeedbackCaptureResult(False, reason="unmonitored_channel")
        if discord_user_id in EXCLUDED_FEEDBACK_USER_IDS:
            return FeedbackCaptureResult(False, reason="excluded_user")

        if thread_title and thread_title.strip():
            existing_thread = self.feedback.get_first_by_thread(
                normalized_channel,
                thread_title,
            )
            if existing_thread is not None:
                return FeedbackCaptureResult(
                    False,
                    feedback_id=int(existing_thread["id"]),
                    reason="duplicate_thread",
                )

        message_type = classify_message(content)
        analysis = self.analyzer.analyze(content, message_type)
        if analysis is None:
            message_type = CHANNEL_DEFAULT_MESSAGE_TYPES[normalized_channel]
            analysis = self.analyzer.analyze(content, message_type)
        if analysis is None:
            return FeedbackCaptureResult(False, reason="not_feedback")

        duplicate = self._find_duplicate_feedback(
            discord_user_id=discord_user_id,
            channel_name=normalized_channel,
            thread_title=thread_title,
            content=content,
        )
        if duplicate is not None:
            return FeedbackCaptureResult(
                False,
                feedback_id=int(duplicate["id"]),
                reason="duplicate_feedback",
            )

        feedback_id = self.feedback.create(
            discord_user_id=discord_user_id,
            discord_user_name=discord_user_name,
            channel_id=channel_id,
            channel_name=normalized_channel,
            thread_title=thread_title,
            content=content,
            category=analysis.category,
            feature=analysis.feature,
            keywords=", ".join(analysis.keywords),
            sentiment=analysis.sentiment,
            priority=analysis.priority,
        )
        return FeedbackCaptureResult(True, feedback_id=feedback_id)

    def _find_duplicate_feedback(
        self,
        *,
        discord_user_id: str,
        channel_name: str,
        thread_title: str | None,
        content: str,
    ):
        normalized_content = normalize_feedback_content(content)
        if not normalized_content:
            return None

        for existing in self.feedback.list_recent_for_dedupe(
            discord_user_id=discord_user_id,
            channel_name=channel_name,
            thread_title=thread_title,
        ):
            existing_content = normalize_feedback_content(str(existing["content"]))
            if not existing_content:
                continue
            if existing_content == normalized_content:
                return existing
            similarity = SequenceMatcher(None, existing_content, normalized_content).ratio()
            if similarity >= DUPLICATE_SIMILARITY_THRESHOLD:
                return existing
        return None


def normalize_feedback_channel_name(channel_name: str | None) -> str:
    if not channel_name:
        return ""
    normalized = channel_name.strip().lower()
    if "│" in normalized:
        normalized = normalized.rsplit("│", maxsplit=1)[-1]
    if "|" in normalized:
        normalized = normalized.rsplit("|", maxsplit=1)[-1]
    return normalized.strip()


def normalize_feedback_content(content: str) -> str:
    normalized = content.lower().strip()
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()
