from __future__ import annotations

from datetime import date
from pathlib import Path

from app.database.db import db_session
from app.database.migrations.init_db import init_database
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.database.repositories.pending_ticket_repository import (
    PendingTicketNoteRepository,
    PendingTicketRepository,
)
from app.dashboard.views.pending_issues import (
    _build_issue_calendar_html,
    _date_marker,
    _extract_resolution_ids,
)


def test_pending_ticket_note_repository_creates_and_lists_notes(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    ticket_id = PendingTicketRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )
    notes = PendingTicketNoteRepository(db_path)

    note_id = notes.create(
        ticket_id=ticket_id,
        operator_name="Operator A",
        note="Asked player for screenshot.",
    )

    ticket_notes = notes.list_by_ticket(ticket_id)
    assert len(ticket_notes) == 1
    assert ticket_notes[0]["id"] == note_id
    assert ticket_notes[0]["operator_name"] == "Operator A"
    assert ticket_notes[0]["note"] == "Asked player for screenshot."


def test_pending_ticket_note_recent_join_includes_ticket_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    ticket_id = PendingTicketRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )
    PendingTicketNoteRepository(db_path).create(ticket_id, "Followed up.")

    row = PendingTicketNoteRepository(db_path).list_recent(1)[0]

    assert row["ticket_id"] == ticket_id
    assert row["discord_user_id"] == "discord-1"
    assert row["status"] == "Open"


def test_pending_ticket_notes_cascade_delete_with_ticket(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    ticket_id = PendingTicketRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )
    notes = PendingTicketNoteRepository(db_path)
    notes.create(ticket_id, "Temporary note.")

    with db_session(db_path) as connection:
        connection.execute("DELETE FROM pending_tickets WHERE id = ?", (ticket_id,))

    assert notes.list_by_ticket(ticket_id) == []


def test_pending_ticket_repository_marks_ticket_resolved(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    tickets = PendingTicketRepository(db_path)
    ticket_id = tickets.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )

    tickets.mark_resolved(ticket_id, assigned_to="Operator A")

    row = tickets.list_recent(1)[0]
    assert row["id"] == ticket_id
    assert row["status"] == "Closed"
    assert row["assigned_to"] == "Operator A"


def test_pending_ticket_repository_deletes_ticket_and_notes(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    tickets = PendingTicketRepository(db_path)
    notes = PendingTicketNoteRepository(db_path)
    ticket_id = tickets.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )
    notes.create(ticket_id, "Resolved in Discord.")

    tickets.delete(ticket_id)

    assert tickets.list_recent(10) == []
    assert notes.list_by_ticket(ticket_id) == []


def test_pending_ticket_repository_includes_channel_display_name(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    DiscordChannelRepository(db_path).upsert(
        channel_id="channel-1",
        channel_name="game-chat",
        channel_type="TextChannel",
        guild_id="guild-1",
    )
    ticket_id = PendingTicketRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )

    row = PendingTicketRepository(db_path).list_recent(1)[0]

    assert row["id"] == ticket_id
    assert row["channel_display_name"] == "game-chat"


def test_discord_channel_repository_lists_uncached_reference_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    tickets = PendingTicketRepository(db_path)
    tickets.create(
        discord_user_id="discord-1",
        channel_id="known-channel",
        original_message="Known",
    )
    tickets.create(
        discord_user_id="discord-2",
        channel_id="unknown-channel",
        original_message="Unknown",
    )
    channels = DiscordChannelRepository(db_path)
    channels.upsert("known-channel", "game-chat")

    assert channels.list_uncached_reference_ids() == ["unknown-channel"]


def test_discord_channel_repository_lists_publishable_channels(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    channels = DiscordChannelRepository(db_path)
    channels.upsert("text-1", "game-chat", "TextChannel", "guild-1")
    channels.upsert("forum-1", "bug-report", "ForumChannel", "guild-1")
    channels.upsert("thread-1", "private-thread", "Thread", "guild-1")

    rows = channels.list_publishable()

    assert [row["channel_id"] for row in rows] == ["forum-1", "text-1"]


def test_extract_resolution_ids_skips_unchecked_and_closed_rows() -> None:
    rows = [
        {"id": 1, "status": "Open", "标记已解决": True},
        {"id": 2, "status": "Open", "标记已解决": False},
        {"id": 3, "status": "Closed", "标记已解决": True},
    ]

    assert _extract_resolution_ids(rows) == [1]


def test_date_marker_uses_open_counts_until_today() -> None:
    today = date(2026, 8, 6)

    assert _date_marker(date(2026, 8, 5), today, {"2026-08-05": 2}) == "red"
    assert _date_marker(date(2026, 8, 6), today, {}) == "green"
    assert _date_marker(date(2026, 8, 7), today, {}) is None


def test_issue_calendar_html_contains_quantity_badges() -> None:
    html = _build_issue_calendar_html(
        date(2026, 8, 1),
        today=date(2026, 8, 6),
        day_stats={
            "2026-08-05": {"new": 2, "open": 1, "closed": 0, "overdue": 0, "high": 0},
            "2026-08-06": {"new": 0, "open": 0, "closed": 1, "overdue": 0, "high": 0},
        },
    )

    assert "pending-badge warn" in html
    assert "issue-calendar-day today" in html
    assert "issue-calendar-dot green" not in html


def test_pending_ticket_repository_counts_open_tickets_by_date(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    tickets = PendingTicketRepository(db_path)
    open_id = tickets.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )
    closed_id = tickets.create(
        discord_user_id="discord-2",
        channel_id="channel-1",
        original_message="Already fixed",
        status="Closed",
    )
    next_day_id = tickets.create(
        discord_user_id="discord-3",
        channel_id="channel-1",
        original_message="Need another help",
    )

    with db_session(db_path) as connection:
        connection.execute(
            "UPDATE pending_tickets SET created_time = ? WHERE id = ?",
            ("2026-08-05 10:00:00", open_id),
        )
        connection.execute(
            "UPDATE pending_tickets SET created_time = ? WHERE id = ?",
            ("2026-08-05 11:00:00", closed_id),
        )
        connection.execute(
            "UPDATE pending_tickets SET created_time = ? WHERE id = ?",
            ("2026-08-06 09:00:00", next_day_id),
        )

    counts = tickets.count_open_by_date_between("2026-08-05", "2026-08-06")

    assert counts == {"2026-08-05": 1, "2026-08-06": 1}
