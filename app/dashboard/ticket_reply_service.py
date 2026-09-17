from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.bot.direct_messenger import DiscordDirectMessenger
from app.database.repositories.pending_ticket_repository import (
    PendingTicketNoteRepository,
    PendingTicketRepository,
)
from config.settings import get_settings


class DirectMessenger(Protocol):
    def send_dm(self, discord_user_id: str, content: str):
        """Send a direct message to a Discord user."""


@dataclass(frozen=True)
class TicketReplyResult:
    ticket_id: int
    discord_user_id: str
    dm_channel_id: str
    discord_message_id: str
    status: str


class TicketReplyService:
    def __init__(
        self,
        db_path: str | Path | None = None,
        messenger: DirectMessenger | None = None,
    ) -> None:
        self.tickets = PendingTicketRepository(db_path)
        self.notes = PendingTicketNoteRepository(db_path)
        settings = get_settings()
        if messenger:
            self.messenger = messenger
        else:
            if not settings.discord_bot_token:
                raise RuntimeError("DISCORD_BOT_TOKEN is required to send Discord replies.")
            self.messenger = DiscordDirectMessenger(
                settings.discord_bot_token,
                proxy=settings.discord_proxy,
            )

    def reply_to_ticket(
        self,
        ticket_id: int,
        reply: str,
        operator_name: str | None = None,
        close_ticket: bool = False,
    ) -> TicketReplyResult:
        clean_reply = reply.strip()
        if not clean_reply:
            raise ValueError("Reply content is required.")

        ticket = self.tickets.get_by_id(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket #{ticket_id} does not exist.")

        send_result = self.messenger.send_dm(str(ticket["discord_user_id"]), clean_reply)
        next_status = "Closed" if close_ticket else "Answered"
        self.tickets.update_status(ticket_id, next_status, operator_name)
        self.notes.create(
            ticket_id=ticket_id,
            operator_name=operator_name,
            note=(
                "Sent DM reply to player.\n\n"
                f"Discord message ID: {send_result.message_id}\n\n"
                f"Reply:\n{clean_reply}"
            ),
        )
        return TicketReplyResult(
            ticket_id=ticket_id,
            discord_user_id=str(ticket["discord_user_id"]),
            dm_channel_id=str(send_result.channel_id),
            discord_message_id=str(send_result.message_id),
            status=next_status,
        )
