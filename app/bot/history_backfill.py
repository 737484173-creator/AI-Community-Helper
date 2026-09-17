from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord

from app.bot.message_handler import IncomingDiscordMessage, MessageHandler
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.utils.time_utils import format_local_datetime


logger = logging.getLogger(__name__)


@dataclass
class HistoryBackfillResult:
    guilds_scanned: int = 0
    channels_scanned: int = 0
    messages_seen: int = 0
    messages_inserted: int = 0
    messages_existing: int = 0
    messages_skipped: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AutomaticBackfillRun:
    after: datetime
    result: HistoryBackfillResult


class DiscordReconnectBackfillCoordinator:
    """Coordinate one initial history scan and a scan after every disconnect.

    A small overlap protects messages received while Discord is detecting the
    lost connection. Repeated scans are safe because messages are deduplicated
    by their Discord message ID in ``MessageRepository``.
    """

    def __init__(
        self,
        service: "DiscordHistoryBackfillService",
        *,
        initial_lookback_hours: int = 24,
        overlap_minutes: int = 5,
    ) -> None:
        if initial_lookback_hours < 0:
            raise ValueError("initial_lookback_hours cannot be negative")
        if overlap_minutes < 0:
            raise ValueError("overlap_minutes cannot be negative")
        self.service = service
        self.initial_lookback_hours = initial_lookback_hours
        self.overlap = timedelta(minutes=overlap_minutes)
        self._initial_scan_completed = False
        self._disconnected_at: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.initial_lookback_hours > 0

    def mark_disconnected(self, disconnected_at: datetime | None = None) -> None:
        if not self.enabled or self._disconnected_at is not None:
            return
        self._disconnected_at = disconnected_at or datetime.now(timezone.utc)

    async def run_pending(
        self,
        guilds,
        *,
        now: datetime | None = None,
    ) -> AutomaticBackfillRun | None:
        if not self.enabled:
            return None

        async with self._lock:
            if self._initial_scan_completed and self._disconnected_at is None:
                return None

            current_time = now or datetime.now(timezone.utc)
            disconnected_at = self._disconnected_at
            if disconnected_at is None:
                after = current_time - timedelta(hours=self.initial_lookback_hours)
            else:
                after = disconnected_at - self.overlap

            result = await self.service.backfill_guilds(guilds, after=after)
            self._initial_scan_completed = True
            # Do not discard a newer disconnect recorded while this scan was
            # running; the next ready event must still cover that gap.
            if self._disconnected_at == disconnected_at:
                self._disconnected_at = None
            return AutomaticBackfillRun(after=after, result=result)


class DiscordHistoryBackfillService:
    """Import every readable, user-authored guild message into the activity store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.handler = MessageHandler(db_path)
        self.channels = DiscordChannelRepository(db_path)

    async def backfill_guilds(
        self,
        guilds,
        *,
        after: datetime | None = None,
    ) -> HistoryBackfillResult:
        result = HistoryBackfillResult()
        for guild in guilds:
            result.guilds_scanned += 1
            channels = await self._discover_message_channels(guild, result, after=after)
            for channel in channels:
                await self._backfill_channel(channel, guild, after, result)
        return result

    async def _discover_message_channels(
        self,
        guild,
        result: HistoryBackfillResult,
        *,
        after: datetime | None,
    ) -> list:
        discovered: dict[str, object] = {}

        def remember(channel) -> None:
            if callable(getattr(channel, "history", None)):
                discovered[str(channel.id)] = channel

        parent_channels = list(getattr(guild, "channels", ()))
        for channel in parent_channels:
            remember(channel)

        try:
            for thread in await guild.active_threads():
                remember(thread)
        except (discord.Forbidden, discord.HTTPException) as exc:
            result.warnings.append(f"服务器 {guild.id} 的活跃帖子读取失败：{exc}")

        for parent in parent_channels:
            archived_threads = getattr(parent, "archived_threads", None)
            if not callable(archived_threads):
                continue
            try:
                async for thread in archived_threads(limit=None):
                    if _was_archived_before(thread, after):
                        break
                    remember(thread)
            except (discord.Forbidden, discord.HTTPException) as exc:
                result.warnings.append(f"频道 {parent.id} 的归档帖子读取失败：{exc}")

            if isinstance(parent, discord.TextChannel):
                try:
                    async for thread in archived_threads(
                        private=True,
                        joined=True,
                        limit=None,
                    ):
                        if _was_archived_before(thread, after):
                            break
                        remember(thread)
                except (discord.Forbidden, discord.HTTPException) as exc:
                    result.warnings.append(f"频道 {parent.id} 的私密归档帖子读取失败：{exc}")

        return list(discovered.values())

    async def _backfill_channel(
        self,
        channel,
        guild,
        after: datetime | None,
        result: HistoryBackfillResult,
    ) -> None:
        channel_name = str(getattr(channel, "name", channel.id))
        seen_before = result.messages_seen
        inserted_before = result.messages_inserted
        self.channels.upsert(
            channel_id=str(channel.id),
            channel_name=channel_name,
            channel_type=channel.__class__.__name__,
            guild_id=str(guild.id),
        )
        try:
            async for message in channel.history(
                limit=None,
                after=after,
                oldest_first=True,
            ):
                result.messages_seen += 1
                if getattr(message.author, "bot", False) or getattr(
                    message,
                    "webhook_id",
                    None,
                ) is not None:
                    result.messages_skipped += 1
                    continue

                handled = self.handler.handle_incoming_message(
                    IncomingDiscordMessage(
                        discord_user_id=str(message.author.id),
                        channel_id=str(channel.id),
                        content=_message_content_for_storage(message),
                        message_source="CHANNEL",
                        discord_message_id=str(message.id),
                        created_time=format_local_datetime(message.created_at),
                        discord_user_name=_discord_display_name(message.author),
                        mentioned_users=tuple(
                            (str(user.id), display_name)
                            for user in getattr(message, "mentions", ())
                            if (display_name := _discord_display_name(user))
                        ),
                    )
                )
                if handled.is_new_message:
                    result.messages_inserted += 1
                else:
                    result.messages_existing += 1
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            result.warnings.append(f"频道 {channel.id}（{channel_name}）消息读取失败：{exc}")
            return

        result.channels_scanned += 1
        logger.info(
            "Backfilled Discord channel guild=%s channel=%s seen=%s inserted=%s",
            guild.id,
            channel.id,
            result.messages_seen - seen_before,
            result.messages_inserted - inserted_before,
        )


class _HistoryBackfillClient(discord.Client):
    def __init__(
        self,
        service: DiscordHistoryBackfillService,
        *,
        after: datetime | None,
        proxy: str | None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        options: dict[str, object] = {"intents": intents}
        if proxy:
            options["proxy"] = proxy
        super().__init__(**options)
        self.service = service
        self.after = after
        self.result: HistoryBackfillResult | None = None
        self.failure: BaseException | None = None
        self._started = False

    async def on_ready(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            self.result = await self.service.backfill_guilds(self.guilds, after=self.after)
        except BaseException as exc:  # surfaced to the synchronous CLI after close
            self.failure = exc
        finally:
            await self.close()


def parse_backfill_since(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        local_zone = datetime.now().astimezone().tzinfo
        parsed = parsed.replace(tzinfo=local_zone)
    return parsed.astimezone(timezone.utc)


def run_history_backfill(
    *,
    token: str,
    db_path: str | Path,
    proxy: str | None = None,
    since: str | None = None,
) -> HistoryBackfillResult:
    client = _HistoryBackfillClient(
        DiscordHistoryBackfillService(db_path),
        after=parse_backfill_since(since),
        proxy=proxy,
    )
    client.run(token, log_handler=None)
    if client.failure is not None:
        raise client.failure
    if client.result is None:
        raise RuntimeError("Discord history backfill ended before a result was produced.")
    return client.result


def _discord_display_name(user) -> str | None:
    display_name = (
        getattr(user, "display_name", None)
        or getattr(user, "global_name", None)
        or getattr(user, "name", None)
    )
    return str(display_name) if display_name else None


def _message_content_for_storage(message) -> str:
    content = str(getattr(message, "content", "") or "").strip()
    if content:
        return content
    if getattr(message, "attachments", None):
        return "[附件消息]"
    if getattr(message, "stickers", None):
        return "[贴纸消息]"
    return "[非文本消息]"


def _was_archived_before(thread, after: datetime | None) -> bool:
    """Whether an archived-thread listing has moved past the requested window."""
    if after is None:
        return False
    archived_at = getattr(thread, "archive_timestamp", None)
    if archived_at is None:
        return False
    if archived_at.tzinfo is None:
        archived_at = archived_at.replace(tzinfo=timezone.utc)
    return archived_at <= after
