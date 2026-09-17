from __future__ import annotations

from pathlib import Path

from app.dashboard.export_utils import records_to_csv
from app.database.db import db_session
from app.database.migrations.init_db import init_database
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository


def test_message_repository_filters_by_time_and_type(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    messages = MessageRepository(db_path)
    messages.create("discord-1", "channel-1", "FAQ question", message_type="FAQ")
    messages.create("discord-2", "channel-1", "Bug report", message_type="BUG")
    with db_session(db_path) as connection:
        connection.execute("UPDATE messages SET created_time = '2026-07-30 10:00:00'")

    rows = messages.list_between(
        "2026-07-30 00:00:00",
        "2026-07-30 23:59:59",
        message_type="FAQ",
    )

    assert len(rows) == 1
    assert rows[0]["message_type"] == "FAQ"


def test_feedback_repository_filters_by_category_priority_and_status(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    feedback = FeedbackRepository(db_path)
    feedback.create("discord-1", "Crash", "BUG", priority="High")
    feedback.create("discord-2", "Reward low", "REWARD_ISSUE", priority="Medium")
    with db_session(db_path) as connection:
        connection.execute("UPDATE feedback SET created_time = '2026-07-30 10:00:00'")

    rows = feedback.list_filtered(
        "2026-07-30 00:00:00",
        "2026-07-30 23:59:59",
        category="BUG",
        priority="High",
        status="Open",
    )

    assert len(rows) == 1
    assert rows[0]["category"] == "BUG"


def test_pending_ticket_repository_filters_by_status(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    tickets = PendingTicketRepository(db_path)
    open_id = tickets.create("discord-1", "channel-1", "Open issue")
    closed_id = tickets.create("discord-2", "channel-1", "Closed issue")
    tickets.update_status(closed_id, "Closed")
    with db_session(db_path) as connection:
        connection.execute("UPDATE pending_tickets SET created_time = '2026-07-30 10:00:00'")

    rows = tickets.list_filtered(
        "2026-07-30 00:00:00",
        "2026-07-30 23:59:59",
        status="Open",
    )

    assert len(rows) == 1
    assert rows[0]["id"] == open_id


def test_pending_ticket_repository_lists_only_ai_dm_unresolved_tickets(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    tickets = PendingTicketRepository(db_path)
    ai_ticket_id = tickets.create("discord-1", "dm-1", "Unknown question")
    tickets.create(
        "discord-2",
        "channel-1",
        "Manual command ticket",
        ticket_source="COMMAND_TICKET",
    )
    tickets.create(
        "discord-3",
        "dm-2",
        "FAQ flow unresolved",
        ticket_source="FAQ_FLOW_UNRESOLVED",
    )
    with db_session(db_path) as connection:
        connection.execute("UPDATE pending_tickets SET created_time = '2026-07-30 10:00:00'")

    rows = tickets.list_ai_dm_unresolved_filtered(
        "2026-07-30 00:00:00",
        "2026-07-30 23:59:59",
    )

    assert len(rows) == 1
    assert rows[0]["id"] == ai_ticket_id


def test_event_repository_filters_by_status_and_type(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    events = EventRepository(db_path)
    poll_id = events.create(
        "Weekly Poll",
        "Pick one mode.",
        "Poll",
        "channel-1",
        "2026-07-30 18:00:00",
        status="Scheduled",
    )
    events.create(
        "Maintenance",
        "Maintenance soon.",
        "Announcement",
        "channel-1",
        "2026-07-30 18:00:00",
        status="Published",
    )

    rows = events.list_filtered(status="Scheduled", event_type="Poll")

    assert len(rows) == 1
    assert rows[0]["id"] == poll_id


def test_records_to_csv_exports_utf8_sig_csv() -> None:
    csv_bytes = records_to_csv([{"id": 1, "content": "Reward issue"}])

    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    assert b"Reward issue" in csv_bytes
