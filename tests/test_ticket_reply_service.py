from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.dashboard.ticket_reply_service import TicketReplyService
from app.database.migrations.init_db import init_database
from app.database.repositories.pending_ticket_repository import (
    PendingTicketNoteRepository,
    PendingTicketRepository,
)


@dataclass(frozen=True)
class FakeSendResult:
    channel_id: str = "dm-channel-1"
    message_id: str = "discord-message-1"


class FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_dm(self, discord_user_id: str, content: str) -> FakeSendResult:
        self.sent.append((discord_user_id, content))
        return FakeSendResult()


def test_ticket_reply_service_sends_dm_and_marks_answered(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    ticket_id = PendingTicketRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="dm-1",
        original_message="Need manual help",
    )
    messenger = FakeMessenger()

    result = TicketReplyService(db_path, messenger).reply_to_ticket(
        ticket_id=ticket_id,
        reply="Please restart the game and try again.",
        operator_name="Operator A",
    )

    assert messenger.sent == [("discord-1", "Please restart the game and try again.")]
    assert result.status == "Answered"
    ticket = PendingTicketRepository(db_path).get_by_id(ticket_id)
    assert ticket is not None
    assert ticket["status"] == "Answered"
    assert ticket["assigned_to"] == "Operator A"
    notes = PendingTicketNoteRepository(db_path).list_by_ticket(ticket_id)
    assert len(notes) == 1
    assert "Sent DM reply to player." in notes[0]["note"]


def test_ticket_reply_service_can_close_ticket_after_reply(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    ticket_id = PendingTicketRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="dm-1",
        original_message="Need manual help",
    )

    result = TicketReplyService(db_path, FakeMessenger()).reply_to_ticket(
        ticket_id=ticket_id,
        reply="Resolved.",
        close_ticket=True,
    )

    assert result.status == "Closed"
    ticket = PendingTicketRepository(db_path).get_by_id(ticket_id)
    assert ticket is not None
    assert ticket["status"] == "Closed"
