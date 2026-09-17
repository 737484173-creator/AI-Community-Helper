from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.dashboard.feedback_reply_service import FeedbackReplyService
from app.database.migrations.init_db import init_database
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.database.repositories.feedback_action_repository import FeedbackActionRepository
from app.database.repositories.feedback_repository import FeedbackRepository


@dataclass(frozen=True)
class FakeSendResult:
    channel_id: str = "thread-1"
    message_id: str = "discord-message-1"


class FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_channel_message(self, channel_id: str, content: str) -> FakeSendResult:
        self.sent.append((channel_id, content))
        return FakeSendResult(channel_id=channel_id)


class FailingMessenger:
    def send_channel_message(self, channel_id: str, content: str) -> FakeSendResult:
        raise RuntimeError("Discord API unavailable")


def _create_feedback(db_path: Path, channel_id: str = "thread-1") -> int:
    return FeedbackRepository(db_path).create(
        "player-1",
        "The reported issue",
        "BUG",
        channel_id=channel_id,
        channel_name="bug-report",
        thread_title="2v2 leadership boost AGAIN",
    )


def test_feedback_reply_service_sends_clean_reply_to_current_thread(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    DiscordChannelRepository(db_path).upsert(
        "thread-1",
        "2v2 leadership boost AGAIN",
        "Thread",
        "guild-1",
    )
    feedback_id = _create_feedback(db_path)
    messenger = FakeMessenger()

    result = FeedbackReplyService(db_path, messenger).reply_to_feedback(
        "  thread-1  ",
        "2v2 leadership boost AGAIN",
        "  Thanks for the report. We are checking it.  ",
        feedback_id=feedback_id,
    )

    assert messenger.sent == [("thread-1", "Thanks for the report. We are checking it.")]
    assert result.channel_id == "thread-1"
    assert result.discord_message_id == "discord-message-1"
    assert result.action_log_id > 0
    action = FeedbackActionRepository(db_path).list_by_feedback(feedback_id)[0]
    assert action["action_type"] == "BOT_REPLY"
    assert action["content"] == "Thanks for the report. We are checking it."
    assert action["destination_label"] == "2v2 leadership boost AGAIN"
    assert action["discord_channel_id"] == "thread-1"
    assert action["discord_message_id"] == "discord-message-1"


def test_feedback_reply_service_resolves_historical_parent_channel_to_thread(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    channels = DiscordChannelRepository(db_path)
    channels.upsert("forum-1", "bug-report", "ForumChannel", "guild-1")
    channels.upsert("thread-1", "2v2 leadership boost AGAIN", "Thread", "guild-1")
    feedback_id = _create_feedback(db_path, channel_id="forum-1")
    messenger = FakeMessenger()

    FeedbackReplyService(db_path, messenger).reply_to_feedback(
        "forum-1",
        "2v2 leadership boost AGAIN",
        "We are checking it.",
        feedback_id=feedback_id,
    )

    assert messenger.sent == [("thread-1", "We are checking it.")]


@pytest.mark.parametrize(
    ("channel_id", "reply", "message"),
    [
        ("", "Hello", "缺少 Discord 帖子或频道 ID"),
        ("thread-1", "   ", "请输入回复内容"),
    ],
)
def test_feedback_reply_service_validates_required_values(
    tmp_path: Path,
    channel_id: str,
    reply: str,
    message: str,
) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    with pytest.raises(ValueError, match=message):
        FeedbackReplyService(db_path, FakeMessenger()).reply_to_feedback(
            channel_id,
            None,
            reply,
            feedback_id=1,
        )


def test_feedback_reply_service_does_not_log_failed_send(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    DiscordChannelRepository(db_path).upsert(
        "thread-1",
        "2v2 leadership boost AGAIN",
        "Thread",
        "guild-1",
    )
    feedback_id = _create_feedback(db_path)

    with pytest.raises(RuntimeError, match="Discord API unavailable"):
        FeedbackReplyService(db_path, FailingMessenger()).reply_to_feedback(
            "thread-1",
            "2v2 leadership boost AGAIN",
            "We are checking it.",
            feedback_id=feedback_id,
        )

    assert FeedbackActionRepository(db_path).list_by_feedback(feedback_id) == []


def test_feedback_reply_service_requires_feedback_id(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    with pytest.raises(ValueError, match="有效记录 ID"):
        FeedbackReplyService(db_path, FakeMessenger()).reply_to_feedback(
            "thread-1",
            None,
            "Hello",
            feedback_id=0,
        )
