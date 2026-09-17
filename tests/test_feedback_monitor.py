from pathlib import Path
from types import SimpleNamespace

from app.bot.feedback_monitor import (
    EXCLUDED_FEEDBACK_USER_IDS,
    MONITORED_FEEDBACK_CHANNELS,
    PublicFeedbackMonitor,
    feedback_source_from_channel,
    normalize_feedback_content,
    normalize_feedback_channel_name,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.feedback_repository import FeedbackRepository


def test_normalize_feedback_channel_name_ignores_emoji_prefix() -> None:
    assert normalize_feedback_channel_name("🐛│bug-report") == "bug-report"
    assert normalize_feedback_channel_name("🔊│game-suggestions") == "game-suggestions"
    assert normalize_feedback_channel_name("🥝|suggestion-discussion") == "suggestion-discussion"


def test_feedback_source_uses_thread_id_and_parent_channel_name() -> None:
    parent = SimpleNamespace(id=10, name="bug-report")
    thread = SimpleNamespace(id=20, name="2v2 leadership boost AGAIN", parent=parent)

    source = feedback_source_from_channel(thread)

    assert source.channel_id == "20"
    assert source.channel_name == "bug-report"
    assert source.thread_title == "2v2 leadership boost AGAIN"


def test_feedback_source_uses_channel_id_when_not_in_thread() -> None:
    channel = SimpleNamespace(id=30, name="bug-report", parent=None)

    source = feedback_source_from_channel(channel)

    assert source.channel_id == "30"
    assert source.channel_name == "bug-report"
    assert source.thread_title is None


def test_feedback_monitor_uses_only_work_order_channels() -> None:
    assert MONITORED_FEEDBACK_CHANNELS == (
        "bug-report",
        "feedback_wanted",
        "game-suggestions",
    )


def test_normalize_feedback_content_ignores_case_and_punctuation() -> None:
    assert normalize_feedback_content("Bug!! Of the SAME type.") == "bug of the same type"


def test_public_feedback_monitor_captures_monitored_channel_feedback(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = PublicFeedbackMonitor(db_path).capture_if_needed(
        discord_user_id="player-1",
        channel_id="channel-1",
        channel_name="🐛│bug-report",
        content="bug of the same type",
    )

    assert result.captured is True
    feedback = FeedbackRepository(db_path).list_recent(1)[0]
    assert feedback["channel_name"] == "bug-report"
    assert feedback["category"] == "BUG"


def test_public_feedback_monitor_captures_feedback_wanted_forum(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = PublicFeedbackMonitor(db_path).capture_if_needed(
        discord_user_id="player-1",
        channel_id="channel-1",
        channel_name="🙋│feedback_wanted",
        thread_title="Improve event rewards",
        content="Please add a preview for the next event reward.",
    )

    assert result.captured is True
    feedback = FeedbackRepository(db_path).list_recent(1)[0]
    assert feedback["channel_name"] == "feedback_wanted"


def test_public_feedback_monitor_skips_chat_oriented_channels(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    monitor = PublicFeedbackMonitor(db_path)

    for channel_name in ("📌│ask_for_help", "🥝│suggestion-discussion"):
        result = monitor.capture_if_needed(
            discord_user_id="player-1",
            channel_id="channel-1",
            channel_name=channel_name,
            content="This game is broken!!!",
        )
        assert result.captured is False
        assert result.reason == "unmonitored_channel"

    assert FeedbackRepository(db_path).list_recent(10) == []


def test_public_feedback_monitor_skips_duplicate_feedback(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    monitor = PublicFeedbackMonitor(db_path)

    first = monitor.capture_if_needed(
        discord_user_id="player-1",
        channel_id="channel-1",
        channel_name="🐛│bug-report",
        content="Bug of the same type; just in different scenio",
    )
    second = monitor.capture_if_needed(
        discord_user_id="player-1",
        channel_id="channel-1",
        channel_name="🐛│bug-report",
        content="bug of the SAME type just in different scenio!",
    )

    assert first.captured is True
    assert second.captured is False
    assert second.reason == "duplicate_feedback"
    assert second.feedback_id == first.feedback_id
    assert len(FeedbackRepository(db_path).list_recent(10)) == 1


def test_public_feedback_monitor_keeps_only_first_feedback_from_same_thread(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    monitor = PublicFeedbackMonitor(db_path)

    first = monitor.capture_if_needed(
        discord_user_id="player-1",
        channel_id="channel-1",
        channel_name="bug-report",
        thread_title="SSR chest rewards",
        content="S20 has not received the SSR shard chest reward.",
    )
    reply = monitor.capture_if_needed(
        discord_user_id="player-2",
        channel_id="channel-1",
        channel_name="bug-report",
        thread_title="SSR chest rewards",
        content="S23 has the same problem and only receives one shard.",
    )

    rows = FeedbackRepository(db_path).list_recent(10)
    assert first.captured is True
    assert reply.captured is False
    assert reply.reason == "duplicate_thread"
    assert reply.feedback_id == first.feedback_id
    assert len(rows) == 1
    assert rows[0]["discord_user_id"] == "player-1"
    assert rows[0]["content"] == "S20 has not received the SSR shard chest reward."


def test_public_feedback_monitor_allows_same_title_in_different_channels(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    monitor = PublicFeedbackMonitor(db_path)

    first = monitor.capture_if_needed(
        discord_user_id="player-1",
        channel_id="channel-1",
        channel_name="bug-report",
        thread_title="Reward issue",
        content="The event reward is missing.",
    )
    second = monitor.capture_if_needed(
        discord_user_id="player-2",
        channel_id="channel-2",
        channel_name="game-suggestions",
        thread_title="Reward issue",
        content="Please add more event rewards.",
    )

    assert first.captured is True
    assert second.captured is True
    assert len(FeedbackRepository(db_path).list_recent(10)) == 2


def test_public_feedback_monitor_excludes_admin_reply(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = PublicFeedbackMonitor(db_path).capture_if_needed(
        discord_user_id=EXCLUDED_FEEDBACK_USER_IDS[0],
        channel_id="channel-1",
        channel_name="🐛│bug-report",
        content="bug of the same type",
    )

    assert result.captured is False
    assert FeedbackRepository(db_path).list_recent(1) == []


def test_feedback_repository_filters_monitored_channels_and_excluded_users(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = FeedbackRepository(db_path)
    repository.create("player-1", "bug", "BUG", channel_id="1", channel_name="bug-report")
    repository.create("player-2", "bug", "BUG", channel_id="2", channel_name="game-chat")
    repository.create(EXCLUDED_FEEDBACK_USER_IDS[0], "bug", "BUG", channel_id="3", channel_name="bug-report")

    rows = repository.list_filtered(
        start_time="2000-01-01 00:00:00",
        end_time="2099-01-01 00:00:00",
        channel_names=("bug-report",),
        excluded_user_ids=EXCLUDED_FEEDBACK_USER_IDS,
    )

    assert len(rows) == 1
    assert rows[0]["discord_user_id"] == "player-1"


def test_feedback_repository_counts_resolved_feedback_with_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = FeedbackRepository(db_path)
    resolved_id = repository.create(
        "player-1",
        "bug",
        "BUG",
        channel_id="1",
        channel_name="bug-report",
    )
    repository.update_status(resolved_id, "Resolved")
    repository.create("player-2", "bug", "BUG", channel_id="2", channel_name="bug-report")
    ignored_channel_id = repository.create(
        "player-3",
        "bug",
        "BUG",
        channel_id="3",
        channel_name="game-chat",
    )
    repository.update_status(ignored_channel_id, "Resolved")
    excluded_id = repository.create(
        EXCLUDED_FEEDBACK_USER_IDS[0],
        "bug",
        "BUG",
        channel_id="4",
        channel_name="bug-report",
    )
    repository.update_status(excluded_id, "Resolved")

    assert repository.count_by_status(
        "Resolved",
        channel_names=("bug-report",),
        excluded_user_ids=EXCLUDED_FEEDBACK_USER_IDS,
    ) == 1
