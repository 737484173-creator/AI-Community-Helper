from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.ai.report_generator import CommunityReportGenerator
from app.database.db import db_session
from app.database.migrations.init_db import init_database
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.database.repositories.report_repository import ReportRepository
from app.scheduler.report_jobs import ReportJobService


def test_report_generator_builds_summary_from_database(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    _seed_report_data(db_path)

    report = CommunityReportGenerator(db_path).generate_report(
        report_type="Daily",
        start_time="2026-07-30 00:00:00",
        end_time="2026-07-30 23:59:59",
    )

    assert "# Daily Community Report" in report
    assert "- Messages: 2" in report
    assert "- AI replies: 1" in report
    assert "- Feedback items: 2" in report
    assert "- High priority feedback: 1" in report
    assert "- New pending tickets: 1" in report
    assert "- BUG: 1" in report
    assert "- REWARD_ISSUE: 1" in report
    assert "Weekly Poll (Poll): 3 participants, 5 reactions" in report
    assert "Review reward-related complaints" in report


def test_report_job_service_saves_daily_report(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    _seed_report_data(db_path)

    result = ReportJobService(db_path).generate_daily_report(
        now=datetime(2026, 7, 31, 12, 0, 0)
    )

    assert result.report_type == "Daily"
    assert result.start_time == "2026-07-30 00:00:00"
    assert result.end_time == "2026-07-30 23:59:59"

    report = ReportRepository(db_path).list_recent("Daily", 1)[0]
    assert report["id"] == result.report_id
    assert "Daily Community Report" in report["content"]


def test_report_job_service_saves_weekly_report_from_monday_to_sunday(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = ReportJobService(db_path).generate_weekly_report(
        now=datetime(2026, 8, 3, 0, 8, 0)
    )

    assert result.report_type == "Weekly"
    assert result.start_time == "2026-07-27 00:00:00"
    assert result.end_time == "2026-08-02 23:59:59"


def test_report_generator_excludes_dm_from_community_message_count(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    messages = MessageRepository(db_path)
    messages.create(
        discord_user_id="discord-public",
        channel_id="channel-1",
        message="Public message",
        message_source="CHANNEL",
        created_time="2026-07-30 12:00:00",
    )
    messages.create(
        discord_user_id="discord-private",
        channel_id="dm-1",
        message="Private message",
        message_source="DM",
        created_time="2026-07-30 12:00:00",
    )

    report = CommunityReportGenerator(db_path).generate_report(
        report_type="Daily",
        start_time="2026-07-30 00:00:00",
        end_time="2026-07-30 23:59:59",
    )

    assert "- Messages: 1" in report


def test_refresh_existing_reports_recalculates_backfilled_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    reports = ReportRepository(db_path)
    report_id = reports.create(
        report_type="Daily",
        title="Daily Community Report",
        content="## Key Metrics\n- Messages: 0",
        start_time="2026-07-30 00:00:00",
        end_time="2026-07-30 23:59:59",
    )
    MessageRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="Backfilled message",
        message_source="CHANNEL",
        created_time="2026-07-30 12:00:00",
    )

    refreshed = ReportJobService(db_path).refresh_existing_reports()

    assert refreshed == 1
    assert "- Messages: 1" in reports.get_by_id(report_id)["content"]


def test_report_job_service_saves_custom_report(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    _seed_report_data(db_path)

    result = ReportJobService(db_path).generate_custom_report(
        start=datetime(2026, 7, 30, 0, 0, 0),
        end=datetime(2026, 7, 31, 23, 59, 59),
    )

    assert result.report_type == "Custom"
    assert result.start_time == "2026-07-30 00:00:00"
    assert result.end_time == "2026-07-31 23:59:59"
    report = ReportRepository(db_path).list_recent("Custom", 1)[0]
    assert report["report_type"] == "Custom"
    assert "Custom Community Report" in report["content"]


def test_report_job_service_rejects_invalid_custom_range(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    import pytest

    with pytest.raises(ValueError):
        ReportJobService(db_path).generate_custom_report(
            start=datetime(2026, 7, 31, 0, 0, 0),
            end=datetime(2026, 7, 30, 23, 59, 59),
        )


def _seed_report_data(db_path: Path) -> None:
    messages = MessageRepository(db_path)
    first_message_id = messages.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="I cannot login",
        ai_reply="Please restart the game.",
        message_type="FAQ",
    )
    messages.create(
        discord_user_id="discord-2",
        channel_id="channel-1",
        message="Reward is too low",
        message_type="COMPLAINT",
    )

    feedback = FeedbackRepository(db_path)
    feedback.create(
        discord_user_id="discord-1",
        content="I cannot login",
        category="BUG",
        feature="Login",
        sentiment="Negative",
        priority="High",
    )
    feedback.create(
        discord_user_id="discord-2",
        content="Reward is too low",
        category="REWARD_ISSUE",
        feature="Reward",
        sentiment="Negative",
        priority="Medium",
    )

    PendingTicketRepository(db_path).create(
        discord_user_id="discord-3",
        channel_id="channel-1",
        original_message="Unknown issue",
    )

    events = EventRepository(db_path)
    event_id = events.create(
        title="Weekly Poll",
        content="Pick one mode.",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-30 18:00:00",
        status="Scheduled",
        event_options_json='["Arena", "Dungeon"]',
    )
    events.update_status(event_id, "Published", "discord-message-1")
    analytics = EventAnalyticsRepository(db_path)
    analytics_id = analytics.create_initial(event_id, "2026-07-30 18:00:00")
    analytics.update_metrics(
        analytics_id,
        3,
        5,
        '{"option_results": [{"marker": "A", "option": "Arena", "count": 2}, {"marker": "B", "option": "Dungeon", "count": 3}], "raw_reactions": {"A": 2, "B": 3}}',
    )

    # SQLite CURRENT_TIMESTAMP uses the actual clock, so tests pin the inserted rows
    # into the report window after normal repository writes.
    with db_session(db_path) as connection:
        for table in ("messages", "feedback", "pending_tickets"):
            connection.execute(
                f"UPDATE {table} SET created_time = '2026-07-30 12:00:00'"
            )
        connection.execute(
            "UPDATE messages SET created_time = '2026-07-30 12:00:00' WHERE id = ?",
            (first_message_id,),
        )
