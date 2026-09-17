from __future__ import annotations

from pathlib import Path

from app.bot.command_service import BotCommandService
from app.database.migrations.init_db import init_database
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.database.repositories.report_repository import ReportRepository


def test_command_service_creates_ticket(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = BotCommandService(db_path).create_ticket(
        discord_user_id="discord-1",
        channel_id="channel-1",
        issue="I still cannot login.",
        category="Login",
    )

    assert result.ticket_id == 1
    assert "Ticket #1" in result.response
    ticket = PendingTicketRepository(db_path).list_recent(1)[0]
    assert ticket["original_message"] == "I still cannot login."
    assert ticket["selected_category"] == "Login"


def test_command_service_generates_daily_report(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = BotCommandService(db_path).generate_report("daily")

    assert result.report_id == 1
    assert "Generated Daily report #1" in result.response
    report = ReportRepository(db_path).list_recent("Daily", 1)[0]
    assert report["report_type"] == "Daily"


def test_command_service_schedules_event(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = BotCommandService(db_path).schedule_event(
        title="Weekly Poll",
        content="Pick a mode.",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        repeat_rule="weekly:friday:18:00",
        options="Arena,Dungeon",
    )

    assert result.event_id == 1
    assert "Scheduled Poll event #1" in result.response
    event = EventRepository(db_path).list_recent(1)[0]
    assert event["status"] == "Scheduled"
    assert event["repeat_rule"] == "weekly:friday:18:00"
    assert event["event_options_json"] == '["Arena", "Dungeon"]'
