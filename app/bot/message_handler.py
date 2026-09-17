from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ai.support_service import SupportResult, SupportService
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.user_repository import UserRepository
from app.utils.constants import FAQ_HELP_TRIGGERS, MESSAGE_TYPE_OTHER


@dataclass(frozen=True)
class IncomingDiscordMessage:
    discord_user_id: str
    channel_id: str
    content: str
    message_source: str = "CHANNEL"
    discord_message_id: str | None = None
    created_time: str | None = None
    discord_user_name: str | None = None
    mentioned_users: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MessageHandleResult:
    message_id: int
    message_type: str
    should_show_faq_flow: bool
    ai_reply: str | None = None
    matched_faq_id: int | None = None
    pending_ticket_id: int | None = None
    feedback_id: int | None = None
    is_new_message: bool = True


class MessageHandler:
    def __init__(
        self,
        db_path: str | Path | None = None,
        support_service: SupportService | None = None,
    ) -> None:
        self.users = UserRepository(db_path)
        self.messages = MessageRepository(db_path)
        self.support_service = support_service or SupportService(db_path)

    def handle_incoming_message(
        self,
        incoming_message: IncomingDiscordMessage,
    ) -> MessageHandleResult:
        self.users.get_or_create(
            incoming_message.discord_user_id,
            discord_user_name=incoming_message.discord_user_name,
        )
        for mentioned_user_id, mentioned_user_name in incoming_message.mentioned_users:
            self.users.get_or_create(
                mentioned_user_id,
                discord_user_name=mentioned_user_name,
            )
        message_id, is_new_message = self.messages.create_if_new(
            discord_user_id=incoming_message.discord_user_id,
            channel_id=incoming_message.channel_id,
            message=incoming_message.content,
            message_type=MESSAGE_TYPE_OTHER,
            message_source=incoming_message.message_source,
            discord_message_id=incoming_message.discord_message_id,
            created_time=incoming_message.created_time,
        )
        if not is_new_message:
            return MessageHandleResult(
                message_id=message_id,
                message_type=MESSAGE_TYPE_OTHER,
                should_show_faq_flow=False,
                is_new_message=False,
            )

        if incoming_message.message_source != "DM":
            return MessageHandleResult(
                message_id=message_id,
                message_type=MESSAGE_TYPE_OTHER,
                should_show_faq_flow=False,
            )

        should_show_faq = should_show_faq_flow(incoming_message.content)
        if should_show_faq:
            return MessageHandleResult(
                message_id=message_id,
                message_type=MESSAGE_TYPE_OTHER,
                should_show_faq_flow=True,
            )

        support_result = self.support_service.process_player_message(
            message_id=message_id,
            discord_user_id=incoming_message.discord_user_id,
            channel_id=incoming_message.channel_id,
            content=incoming_message.content,
        )

        return _to_handle_result(
            message_id=message_id,
            support_result=support_result,
        )


def should_show_faq_flow(content: str) -> bool:
    normalized = content.strip().lower()
    if normalized in FAQ_HELP_TRIGGERS:
        return True

    return any(trigger in normalized for trigger in FAQ_HELP_TRIGGERS if len(trigger) >= 2)


def _to_handle_result(
    message_id: int,
    support_result: SupportResult,
) -> MessageHandleResult:
    return MessageHandleResult(
        message_id=message_id,
        message_type=support_result.message_type,
        should_show_faq_flow=False,
        ai_reply=support_result.reply,
        matched_faq_id=support_result.matched_faq_id,
        pending_ticket_id=support_result.pending_ticket_id,
        feedback_id=support_result.feedback_id,
    )
