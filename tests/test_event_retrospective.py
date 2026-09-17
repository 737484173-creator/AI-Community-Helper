from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.ai.event_retrospective import EventRetrospectiveService
from app.database.db import db_session
from app.database.migrations.init_db import init_database
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.report_repository import ReportRepository


def test_event_retrospective_generates_report_with_winner_and_feedback(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    event_id = _seed_event_retrospective_data(db_path)

    report_id = EventRetrospectiveService(db_path).generate_for_event(event_id)

    report = ReportRepository(db_path).get_by_id(report_id)
    assert report is not None
    assert report["report_type"] == "EventRetrospective"
    assert "Event Retrospective: Weekly Poll" in report["content"]
    assert "Winning option: B. Dungeon (3 votes)" in report["content"]
    assert "Reward is too low" in report["content"]


def test_event_retrospective_rejects_missing_event(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    import pytest

    with pytest.raises(ValueError):
        EventRetrospectiveService(db_path).generate_for_event(999)


def test_manage_event_retrospective_command(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    event_id = _seed_event_retrospective_data(db_path)

    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "event-retrospective",
            str(event_id),
            "--db-path",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Generated event retrospective report" in result.stdout


def test_manage_event_retrospective_command_reports_missing_event(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "event-retrospective",
            "999",
            "--db-path",
            str(db_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Event not found: 999" in result.stderr


def _seed_event_retrospective_data(db_path: Path) -> int:
    events = EventRepository(db_path)
    event_id = events.create(
        title="Weekly Poll",
        content="Pick one mode.",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        status="Scheduled",
        event_options_json='["Arena", "Dungeon"]',
    )
    events.update_status(event_id, "Published", "discord-message-1")
    analytics = EventAnalyticsRepository(db_path)
    analytics_id = analytics.create_initial(event_id, "2026-07-31 18:00:00")
    analytics.update_metrics(
        analytics_id,
        participant_count=3,
        reaction_count=5,
        poll_result_json='{"option_results": [{"marker": "A", "option": "Arena", "count": 2}, {"marker": "B", "option": "Dungeon", "count": 3}], "raw_reactions": {"A": 2, "B": 3}}',
    )
    FeedbackRepository(db_path).create(
        discord_user_id="discord-1",
        content="Reward is too low",
        category="REWARD_ISSUE",
        sentiment="Negative",
        priority="Medium",
    )
    with db_session(db_path) as connection:
        connection.execute("UPDATE feedback SET created_time = '2026-07-31 19:00:00'")
        connection.execute(
            "UPDATE event_analytics SET updated_time = '2026-07-31 20:00:00'"
        )
    return event_id
