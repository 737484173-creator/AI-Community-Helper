from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.bot.history_backfill import (
    DiscordHistoryBackfillService,
    DiscordReconnectBackfillCoordinator,
    HistoryBackfillResult,
    _was_archived_before,
    parse_backfill_since,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.message_repository import MessageRepository


class FakeAuthor:
    def __init__(self, user_id: str, *, bot: bool = False) -> None:
        self.id = user_id
        self.bot = bot
        self.display_name = f"user-{user_id}"


class FakeMessage:
    def __init__(
        self,
        message_id: str,
        author: FakeAuthor,
        content: str,
        created_at: datetime,
        *,
        attachments=(),
    ) -> None:
        self.id = message_id
        self.author = author
        self.content = content
        self.created_at = created_at
        self.attachments = attachments
        self.stickers = ()
        self.mentions = ()
        self.webhook_id = None


class FakeChannel:
    def __init__(self, channel_id: str, messages: list[FakeMessage]) -> None:
        self.id = channel_id
        self.name = "general"
        self._messages = messages

    def history(self, **_kwargs):
        async def iterate():
            for message in self._messages:
                yield message

        return iterate()


class FakeGuild:
    def __init__(self, channel: FakeChannel) -> None:
        self.id = "guild-1"
        self.channels = [channel]

    async def active_threads(self):
        return []


def test_history_backfill_imports_all_user_messages_and_deduplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    local_zone = datetime.now().astimezone().tzinfo
    created_at = datetime(2026, 7, 30, 12, 0, 0, tzinfo=local_zone)
    channel = FakeChannel(
        "channel-1",
        [
            FakeMessage("message-1", FakeAuthor("user-1"), "hello", created_at),
            FakeMessage(
                "message-2",
                FakeAuthor("user-2"),
                "",
                created_at,
                attachments=(object(),),
            ),
            FakeMessage("message-3", FakeAuthor("bot-1", bot=True), "bot", created_at),
        ],
    )
    service = DiscordHistoryBackfillService(db_path)

    first = asyncio.run(service.backfill_guilds([FakeGuild(channel)]))
    second = asyncio.run(service.backfill_guilds([FakeGuild(channel)]))

    assert first.messages_inserted == 2
    assert first.messages_skipped == 1
    assert second.messages_inserted == 0
    assert second.messages_existing == 2
    rows = MessageRepository(db_path).list_recent(10)
    assert len(rows) == 2
    assert {row["message"] for row in rows} == {"hello", "[附件消息]"}
    assert {row["created_time"] for row in rows} == {"2026-07-30 12:00:00"}


def test_parse_backfill_since_returns_utc_aware_datetime() -> None:
    parsed = parse_backfill_since("2026-07-30")

    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


class FakeBackfillService:
    def __init__(self) -> None:
        self.after_values: list[datetime] = []

    async def backfill_guilds(self, _guilds, *, after: datetime):
        self.after_values.append(after)
        return HistoryBackfillResult(messages_inserted=2)


def test_reconnect_backfill_runs_initial_window_once() -> None:
    async def scenario() -> None:
        service = FakeBackfillService()
        coordinator = DiscordReconnectBackfillCoordinator(
            service,
            initial_lookback_hours=24,
        )
        now = datetime(2026, 9, 10, 4, 0, tzinfo=timezone.utc)

        first = await coordinator.run_pending([], now=now)
        second = await coordinator.run_pending([], now=now + timedelta(minutes=1))

        assert first is not None
        assert first.after == now - timedelta(hours=24)
        assert first.result.messages_inserted == 2
        assert second is None
        assert service.after_values == [now - timedelta(hours=24)]

    asyncio.run(scenario())


def test_reconnect_backfill_uses_disconnect_time_with_overlap() -> None:
    async def scenario() -> None:
        service = FakeBackfillService()
        coordinator = DiscordReconnectBackfillCoordinator(service)
        now = datetime(2026, 9, 10, 4, 0, tzinfo=timezone.utc)
        await coordinator.run_pending([], now=now)
        disconnected_at = now + timedelta(hours=2)
        coordinator.mark_disconnected(disconnected_at)

        run = await coordinator.run_pending([], now=disconnected_at + timedelta(hours=1))

        assert run is not None
        assert run.after == disconnected_at - timedelta(minutes=5)
        assert service.after_values[-1] == disconnected_at - timedelta(minutes=5)

    asyncio.run(scenario())


def test_archived_thread_filter_stops_before_requested_window() -> None:
    class FakeThread:
        archive_timestamp = datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc)

    assert _was_archived_before(
        FakeThread(),
        datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc),
    ) is True
    assert _was_archived_before(FakeThread(), None) is False
