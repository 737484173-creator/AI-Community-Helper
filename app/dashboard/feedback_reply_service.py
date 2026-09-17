from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.bot.direct_messenger import DiscordDirectMessenger
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.database.repositories.feedback_action_repository import FeedbackActionRepository
from config.settings import get_settings


class ChannelMessenger(Protocol):
    def send_channel_message(self, channel_id: str, content: str):
        """Send a message to a Discord channel or thread."""


@dataclass(frozen=True)
class FeedbackReplyResult:
    channel_id: str
    discord_message_id: str
    action_log_id: int


class FeedbackReplyService:
    def __init__(
        self,
        db_path: str | Path | None = None,
        messenger: ChannelMessenger | None = None,
    ) -> None:
        self.channels = DiscordChannelRepository(db_path)
        self.actions = FeedbackActionRepository(db_path)
        if messenger is not None:
            self.messenger = messenger
            return

        settings = get_settings()
        if not settings.discord_bot_token:
            raise RuntimeError("缺少 DISCORD_BOT_TOKEN，无法通过 Discord Bot 回复帖子。")
        self.messenger = DiscordDirectMessenger(
            settings.discord_bot_token,
            proxy=settings.discord_proxy,
        )

    def reply_to_feedback(
        self,
        channel_id: str,
        thread_title: str | None,
        reply: str,
        *,
        feedback_id: int,
    ) -> FeedbackReplyResult:
        clean_reply = reply.strip()
        if not clean_reply:
            raise ValueError("请输入回复内容。")
        if feedback_id <= 0:
            raise ValueError("当前反馈缺少有效记录 ID，无法保存处理记录。")

        target_channel_id = self.resolve_reply_channel(channel_id, thread_title)
        send_result = self.messenger.send_channel_message(target_channel_id, clean_reply)
        resolved_channel_id = str(send_result.channel_id)
        discord_message_id = str(send_result.message_id)
        action_log_id = self.actions.create_bot_reply(
            feedback_id,
            clean_reply,
            resolved_channel_id,
            discord_message_id,
            destination_label=(thread_title or "").strip() or None,
        )
        return FeedbackReplyResult(
            channel_id=resolved_channel_id,
            discord_message_id=discord_message_id,
            action_log_id=action_log_id,
        )

    def resolve_reply_channel(self, channel_id: str, thread_title: str | None) -> str:
        clean_channel_id = channel_id.strip()
        clean_thread_title = (thread_title or "").strip()
        if not clean_channel_id:
            raise ValueError("当前反馈缺少 Discord 帖子或频道 ID，无法回复。")

        source_channel = self.channels.get_by_channel_id(clean_channel_id)
        source_channel_type = str(source_channel["channel_type"] or "") if source_channel else ""
        if source_channel_type == "Thread":
            return clean_channel_id

        if clean_thread_title:
            guild_id = str(source_channel["guild_id"] or "") if source_channel else None
            cached_thread = self.channels.find_thread_by_name(
                clean_thread_title,
                guild_id=guild_id or None,
            )
            if cached_thread is None:
                raise ValueError(
                    f"未找到帖子“{clean_thread_title}”的 Discord 线程，请确认 Bot 已同步该帖子。"
                )
            return str(cached_thread["channel_id"])

        return clean_channel_id
