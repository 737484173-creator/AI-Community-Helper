from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from app.bot.event_analytics_collector import DiscordEventAnalyticsCollector
from app.bot.event_publisher import DiscordEventPublisher
from app.bot.feedback_monitor import PublicFeedbackMonitor, feedback_source_from_channel
from app.bot.history_backfill import (
    DiscordHistoryBackfillService,
    DiscordReconnectBackfillCoordinator,
)
from app.bot.message_handler import IncomingDiscordMessage, MessageHandler
from app.bot.faq_flow import FAQFlowService
from app.bot.discord_views import FAQCategoryView
from app.bot.discord_commands import register_commands
from app.database.migrations.init_db import init_database
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.member_review.service import MemberReviewService
from app.scheduler.scheduler import create_scheduler
from app.utils.single_instance import SingleInstanceLock
from app.utils.time_utils import format_local_datetime
from config.logging_config import configure_logging
from config.settings import get_settings


logger = logging.getLogger(__name__)


def _discord_display_name(user) -> str | None:
    display_name = (
        getattr(user, "display_name", None)
        or getattr(user, "global_name", None)
        or getattr(user, "name", None)
    )
    return str(display_name) if display_name else None


def _message_content_for_storage(message: discord.Message) -> str:
    content = str(getattr(message, "content", "") or "").strip()
    if content:
        return content
    if getattr(message, "attachments", None):
        return "[附件消息]"
    if getattr(message, "stickers", None):
        return "[贴纸消息]"
    return "[非文本消息]"


class CommunityOperationBot(discord.Client):
    def __init__(
        self,
        message_handler: MessageHandler,
        faq_flow: FAQFlowService,
        db_path: str,
        proxy: str | None = None,
        auto_backfill_hours: int = 24,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        client_options = {"intents": intents}
        if proxy:
            client_options["proxy"] = proxy
        super().__init__(**client_options)
        self.message_handler = message_handler
        self.faq_flow = faq_flow
        self.db_path = db_path
        self.channel_repository = DiscordChannelRepository(db_path)
        self.feedback_monitor = PublicFeedbackMonitor(db_path)
        self.member_review_service = MemberReviewService(db_path)
        self.reconnect_backfill = DiscordReconnectBackfillCoordinator(
            DiscordHistoryBackfillService(db_path),
            initial_lookback_hours=auto_backfill_hours,
        )
        self._scheduler_started = False
        self._member_screening_synced = False
        self._history_backfill_tasks: set[asyncio.Task] = set()
        self._active_faq_prompts: dict[str, discord.Message] = {}
        self.tree = app_commands.CommandTree(self)
        register_commands(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        logger.info("Discord slash commands synced.")

    async def on_ready(self) -> None:
        logger.info("Discord bot logged in as %s", self.user)
        self._sync_channel_cache()
        await self._sync_referenced_channel_cache()
        self._schedule_missed_channel_message_backfill()
        self._sync_join_requests()
        await self._sync_pending_members()
        if not self._scheduler_started:
            scheduler = create_scheduler(
                event_publisher=DiscordEventPublisher(self),
                analytics_collector=DiscordEventAnalyticsCollector(self),
                db_path=self.db_path,
            )
            scheduler.start()
            self._scheduler_started = True
            logger.info("Community event scheduler started.")

    async def on_disconnect(self) -> None:
        self.reconnect_backfill.mark_disconnected()
        logger.warning("Discord connection lost; message history backfill queued for reconnect.")

    def _schedule_missed_channel_message_backfill(self) -> None:
        if not self.reconnect_backfill.enabled:
            return
        task = asyncio.create_task(self._backfill_missed_channel_messages())
        self._history_backfill_tasks.add(task)
        task.add_done_callback(self._history_backfill_tasks.discard)

    async def _backfill_missed_channel_messages(self) -> None:
        try:
            run = await self.reconnect_backfill.run_pending(self.guilds)
        except Exception:
            # A history permission or transient API problem must not prevent
            # the live bot from reconnecting and receiving new messages.
            logger.exception("Automatic Discord history backfill failed.")
            return

        if run is None:
            return

        result = run.result
        logger.info(
            "Automatic Discord history backfill completed after=%s guilds=%s "
            "channels=%s seen=%s inserted=%s existing=%s skipped=%s warnings=%s",
            run.after.isoformat(),
            result.guilds_scanned,
            result.channels_scanned,
            result.messages_seen,
            result.messages_inserted,
            result.messages_existing,
            result.messages_skipped,
            len(result.warnings),
        )
        for warning in result.warnings:
            logger.warning("Automatic Discord history backfill warning: %s", warning)

    def _sync_channel_cache(self) -> None:
        for guild in self.guilds:
            for channel in guild.channels:
                self._cache_channel_object(channel, guild_id=str(guild.id))
        logger.info("Discord channel cache synced for %s guild(s).", len(self.guilds))

    async def _sync_referenced_channel_cache(self) -> None:
        uncached_ids = self.channel_repository.list_uncached_reference_ids()
        cached_count = 0
        for channel_id in uncached_ids:
            try:
                channel = await self.fetch_channel(int(channel_id))
            except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError):
                continue

            guild_id = str(channel.guild.id) if getattr(channel, "guild", None) else None
            if self._cache_channel_object(channel, guild_id=guild_id):
                cached_count += 1
        logger.info("Discord referenced channel cache synced: %s/%s.", cached_count, len(uncached_ids))

    def _cache_channel_object(self, channel, guild_id: str | None = None) -> bool:
        channel_name = getattr(channel, "name", None)
        if not channel_name:
            return False

        self.channel_repository.upsert(
            channel_id=str(channel.id),
            channel_name=str(channel_name),
            channel_type=channel.__class__.__name__,
            guild_id=guild_id,
        )
        return True

    def _sync_join_requests(self) -> None:
        guild_ids = [str(guild.id) for guild in self.guilds]
        if not guild_ids:
            return
        try:
            synced = self.member_review_service.sync_discord_join_requests(guild_ids)
        except RuntimeError as exc:
            logger.warning("Discord join request sync failed: %s", exc)
            return
        logger.info("Discord join request sync captured %s request(s).", synced)

    async def _sync_pending_members(self) -> None:
        if self._member_screening_synced:
            return
        self._member_screening_synced = True

        total = 0
        for guild in self.guilds:
            try:
                async for member in guild.fetch_members(limit=None):
                    if self._capture_pending_member(member):
                        total += 1
            except discord.Forbidden:
                logger.warning(
                    "Missing permission or Server Members Intent for member screening sync in guild %s.",
                    guild.id,
                )
            except discord.HTTPException as exc:
                logger.warning("Failed to sync pending members for guild %s: %s", guild.id, exc)
        logger.info("Discord pending member screening sync captured %s member(s).", total)

    def _capture_pending_member(self, member: discord.Member) -> bool:
        if not bool(getattr(member, "pending", False)):
            return False
        display_name = (
            getattr(member, "display_name", None)
            or getattr(member, "global_name", None)
            or getattr(member, "name", None)
            or str(member.id)
        )
        username = (
            getattr(member, "global_name", None)
            or getattr(member, "name", None)
            or str(member)
        )
        application_id = self.member_review_service.ingest_discord_pending_member(
            discord_username=str(username),
            discord_user_id=str(member.id),
            raw_application=str(display_name),
        )
        logger.info(
            "Captured pending member application id=%s user=%s pending=%s",
            application_id,
            member.id,
            getattr(member, "pending", None),
        )
        return True

    async def on_member_join(self, member: discord.Member) -> None:
        self._capture_pending_member(member)

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if bool(getattr(after, "pending", False)):
            self._capture_pending_member(after)

    def _cache_message_channel(self, message: discord.Message) -> None:
        if message.guild is None:
            self.channel_repository.upsert(
                channel_id=str(message.channel.id),
                channel_name="私信",
                channel_type=message.channel.__class__.__name__,
                guild_id=None,
            )
            return

        parent_channel = getattr(message.channel, "parent", None)
        if parent_channel is not None:
            self._cache_channel_object(parent_channel, guild_id=str(message.guild.id))
        channel_name = getattr(message.channel, "name", None)
        if channel_name:
            self._cache_channel_object(message.channel, guild_id=str(message.guild.id))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or getattr(message, "webhook_id", None) is not None:
            return

        raw_content = str(message.content or "").strip()
        if message.guild is None and not raw_content:
            return
        content = raw_content or _message_content_for_storage(message)

        self._cache_message_channel(message)
        result = self.message_handler.handle_incoming_message(
            IncomingDiscordMessage(
                discord_user_id=str(message.author.id),
                channel_id=str(message.channel.id),
                content=content,
                message_source="DM" if message.guild is None else "CHANNEL",
                discord_message_id=str(message.id),
                created_time=format_local_datetime(message.created_at),
                discord_user_name=_discord_display_name(message.author),
                mentioned_users=tuple(
                    (str(user.id), display_name)
                    for user in message.mentions
                    if (display_name := _discord_display_name(user))
                ),
            )
        )
        logger.info(
            "Saved Discord message id=%s type=%s user=%s channel=%s new=%s",
            result.message_id,
            result.message_type,
            message.author.id,
            message.channel.id,
            result.is_new_message,
        )

        if message.guild is not None:
            feedback_source = feedback_source_from_channel(message.channel)
            discord_user_name = _discord_display_name(message.author)
            if raw_content:
                feedback_result = self.feedback_monitor.capture_if_needed(
                    discord_user_id=str(message.author.id),
                    discord_user_name=str(discord_user_name) if discord_user_name else None,
                    channel_id=feedback_source.channel_id,
                    channel_name=feedback_source.channel_name,
                    thread_title=feedback_source.thread_title,
                    content=raw_content,
                )
                if feedback_result.captured:
                    logger.info(
                        "Captured public feedback id=%s user=%s channel=%s",
                        feedback_result.feedback_id,
                        message.author.id,
                        feedback_source.channel_name,
                    )
            return

        if result.should_show_faq_flow:
            categories = self.faq_flow.list_categories()
            if not categories:
                ticket_id = self.faq_flow.create_pending_ticket(
                    discord_user_id=str(message.author.id),
                    channel_id=str(message.channel.id),
                    original_message=content,
                    issue_description="FAQ flow was requested, but no FAQ categories are available.",
                )
                await message.channel.send(
                    "No FAQ knowledge base is available yet. "
                    f"I created ticket #{ticket_id} for manual support."
                )
                return

            await self._send_faq_category_prompt(
                channel=message.channel,
                discord_user_id=str(message.author.id),
                channel_id=str(message.channel.id),
                message_id=result.message_id,
                original_message=content,
            )
            return

        if result.ai_reply:
            await message.channel.send(result.ai_reply)

    async def _send_faq_category_prompt(
        self,
        channel,
        discord_user_id: str,
        channel_id: str,
        message_id: int,
        original_message: str,
    ) -> None:
        previous_prompt = self._active_faq_prompts.pop(discord_user_id, None)
        if previous_prompt:
            try:
                await previous_prompt.delete()
            except discord.HTTPException:
                pass
        await self._delete_recent_faq_prompts(channel)

        prompt = await channel.send(
            "Please select the type of issue you are experiencing:",
            view=FAQCategoryView(
                faq_flow=self.faq_flow,
                message_id=message_id,
                discord_user_id=discord_user_id,
                channel_id=channel_id,
                original_message=original_message,
            ),
        )
        self._active_faq_prompts[discord_user_id] = prompt

    async def _delete_recent_faq_prompts(self, channel) -> None:
        if not hasattr(channel, "history"):
            return

        try:
            async for old_message in channel.history(limit=25):
                if old_message.author != self.user:
                    continue
                if old_message.content != "Please select the type of issue you are experiencing:":
                    continue
                await old_message.delete()
        except discord.HTTPException:
            pass


def run_bot() -> None:
    configure_logging()
    settings = get_settings()
    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required to run the Discord bot.")

    lock_path = settings.db_path.parent / "discord_bot.lock"
    with SingleInstanceLock(lock_path):
        init_database(settings.db_path)
        bot = CommunityOperationBot(
            message_handler=MessageHandler(settings.db_path),
            faq_flow=FAQFlowService(settings.db_path),
            db_path=str(settings.db_path),
            proxy=settings.discord_proxy,
            auto_backfill_hours=settings.discord_auto_backfill_hours,
        )
        bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    run_bot()
