from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.bot.event_publisher import InMemoryEventPublisher, format_event_message
from app.dashboard.views.event_management import (
    _analytics_filter_options,
    _event_day_archive_label,
    _event_effect_archive_date,
    _event_analytics_overview,
    _event_options_json,
    _event_week_archive_label,
    _filter_analytics_rows,
    _format_event_rows,
    _format_analytics_summary_rows,
    _group_event_effects_by_week_day,
    _overdue_scheduled_events,
    _poll_option_results,
    _poll_winner_label,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.scheduler.event_jobs import EventPublishService
from app.scheduler.repeat_rules import calculate_next_publish_time
from app.utils.time_utils import format_datetime, parse_datetime


def test_publish_due_one_time_event(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    events = EventRepository(db_path)
    event_id = events.create(
        title="Maintenance Notice",
        content="Server maintenance starts soon.",
        event_type="Announcement",
        channel_id="channel-1",
        publish_time="2026-07-30 18:00:00",
        repeat_rule="none",
        status="Scheduled",
    )

    publisher = InMemoryEventPublisher()
    results = EventPublishService(publisher, db_path).publish_due_events(
        now=parse_datetime("2026-07-30 18:01:00")
    )

    assert len(results) == 1
    assert results[0].event_id == event_id
    assert results[0].next_publish_time is None
    assert publisher.published_messages[0]["title"] == "Maintenance Notice"

    event = events.list_recent(1)[0]
    assert event["status"] == "Published"
    assert event["discord_message_id"] == "test-message-1"

    analytics = EventAnalyticsRepository(db_path).list_by_event(event_id)
    assert len(analytics) == 1
    assert analytics[0]["published_time"] == "2026-07-30 18:01:00"


def test_publish_due_weekly_event_is_rescheduled(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    events = EventRepository(db_path)
    event_id = events.create(
        title="Weekly Poll",
        content="Which mode do you like most?",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        repeat_rule="weekly:friday:18:00",
        status="Scheduled",
    )

    results = EventPublishService(InMemoryEventPublisher(), db_path).publish_due_events(
        now=parse_datetime("2026-07-31 18:00:01")
    )

    assert len(results) == 1
    assert results[0].event_id == event_id
    assert results[0].next_publish_time == "2026-08-07 18:00:00"

    event = events.list_recent(1)[0]
    assert event["status"] == "Scheduled"
    assert event["publish_time"] == "2026-08-07 18:00:00"


def test_publish_service_ignores_future_events(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    EventRepository(db_path).create(
        title="Future Quiz",
        content="Answer the question tomorrow.",
        event_type="Quiz",
        channel_id="channel-1",
        publish_time="2026-08-01 10:00:00",
        repeat_rule="none",
        status="Scheduled",
    )

    publisher = InMemoryEventPublisher()
    results = EventPublishService(publisher, db_path).publish_due_events(
        now=parse_datetime("2026-07-30 10:00:00")
    )

    assert results == []
    assert publisher.published_messages == []


def test_repeat_rule_calculates_daily_and_weekly_times() -> None:
    publish_time = datetime(2026, 7, 31, 18, 0, 0)

    assert format_datetime(calculate_next_publish_time(publish_time, "daily")) == (
        "2026-08-01 18:00:00"
    )
    assert format_datetime(
        calculate_next_publish_time(publish_time, "weekly:friday:18:00")
    ) == "2026-08-07 18:00:00"
    assert calculate_next_publish_time(publish_time, "none") is None


def test_repeat_rule_rejects_invalid_rule() -> None:
    with pytest.raises(ValueError):
        calculate_next_publish_time(datetime(2026, 7, 31, 18, 0, 0), "hourly")


def test_event_message_format() -> None:
    assert format_event_message("Weekly Poll", "Pick one mode.", "Poll") == (
        "**[Poll] Weekly Poll**\n\nPick one mode."
    )


def test_event_options_are_omitted_for_announcements() -> None:
    assert _event_options_json("Announcement", "Yes\nNo") is None


def test_event_options_are_preserved_for_interactive_types() -> None:
    assert _event_options_json("Poll", "Yes\nNo") == '["Yes", "No"]'
    assert _event_options_json("Survey", "Good\nBad") == '["Good", "Bad"]'
    assert _event_options_json("Quiz", "A\nB") == '["A", "B"]'


def test_event_analytics_poll_results_are_formatted_for_dashboard() -> None:
    poll_result_json = (
        '{"option_results": ['
        '{"marker": "A", "option": "Saris", "count": 1},'
        '{"marker": "B", "option": "Sim", "count": 4}'
        ']}'
    )

    results = _poll_option_results(poll_result_json)
    assert results == [
        {"marker": "A", "option": "Saris", "count": 1},
        {"marker": "B", "option": "Sim", "count": 4},
    ]
    assert _poll_winner_label(results) == "B. Sim (4 票)"

    rows = _format_analytics_summary_rows(
        [
            {
                "event_id": 2,
                "title": "Who's the Bunny bride?",
                "event_type": "Poll",
                "channel_id": "1534",
                "published_time": "2026-08-07 14:54:10",
                "participant_count": 5,
                "reaction_count": 5,
                "poll_result_json": poll_result_json,
            }
        ],
        {"1534": "#ai-support-channel"},
    )

    assert rows == [
        {
            "活动 ID": 2,
            "活动标题": "Who's the Bunny bride?",
            "活动类型": "投票",
            "发布频道": "#ai-support-channel",
            "发布时间": "2026-08-07 14:54:10",
            "参与人数": 5,
            "互动数": 5,
            "当前领先": "B. Sim (4 票)",
        }
    ]


def test_event_analytics_rows_can_be_filtered_by_event() -> None:
    rows = [
        {
            "event_id": 1,
            "title": "First Poll",
            "published_time": "2026-08-07 14:35:07",
        },
        {
            "event_id": 2,
            "title": "Second Poll",
            "published_time": "2026-08-07 14:54:10",
        },
        {
            "event_id": 2,
            "title": "Second Poll",
            "published_time": "2026-08-07 14:54:10",
        },
    ]

    assert _analytics_filter_options(rows) == [
        ("全部活动", None),
        ("#1 · First Poll · 2026-08-07 14:35:07", 1),
        ("#2 · Second Poll · 2026-08-07 14:54:10", 2),
    ]
    assert _filter_analytics_rows(rows, None) == rows
    assert _filter_analytics_rows(rows, 2) == rows[1:]


def test_event_rows_are_formatted_for_operator_table() -> None:
    publish_time = format_datetime(datetime.now().replace(microsecond=0) + timedelta(days=1))
    rows = _format_event_rows(
        [
            {
                "id": 8,
                "title": "Patch Notes Poll",
                "event_type": "Poll",
                "status": "Scheduled",
                "channel_id": "1534",
                "publish_time": publish_time,
                "discord_message_id": None,
            }
        ],
        {"1534": "#ai-support-channel"},
    )

    assert rows == [
        {
            "ID": 8,
            "活动标题": "Patch Notes Poll",
            "类型": "投票",
            "状态": "已排期",
            "发布频道": "#ai-support-channel",
            "发布时间": publish_time,
            "Discord 发布状态": "等待发布时间",
        }
    ]


def test_event_analytics_overview_summarizes_filtered_rows() -> None:
    assert _event_analytics_overview(
        [
            {"event_id": 1, "participant_count": 2, "reaction_count": 3},
            {"event_id": 2, "participant_count": 5, "reaction_count": 7},
            {"event_id": 2, "participant_count": 1, "reaction_count": 2},
        ]
    ) == {
        "活动数": 2,
        "参与人数": 8,
        "互动数": 12,
    }


def test_overdue_scheduled_events_uses_publish_grace_period() -> None:
    records = [
        {
            "id": 1,
            "status": "Scheduled",
            "publish_time": "2026-09-08 17:59:00",
            "discord_message_id": None,
        },
        {
            "id": 2,
            "status": "Scheduled",
            "publish_time": "2026-09-08 17:59:30",
            "discord_message_id": None,
        },
        {
            "id": 3,
            "status": "Published",
            "publish_time": "2026-09-08 17:00:00",
            "discord_message_id": "message-3",
        },
    ]

    assert [row["id"] for row in _overdue_scheduled_events(
        records,
        now=datetime(2026, 9, 8, 18, 0, 15),
    )] == [1]


def test_event_effect_archive_date_falls_back_to_creation_time() -> None:
    assert _event_effect_archive_date(
        {
            "published_time": "invalid",
            "created_time": "2026-09-07 10:30:00",
        }
    ) == date(2026, 9, 7)


def test_event_effects_are_grouped_by_week_and_day_newest_first() -> None:
    rows = [
        {
            "id": 1,
            "event_id": 1,
            "published_time": "2026-09-06 18:00:00",
            "participant_count": 2,
            "reaction_count": 3,
        },
        {
            "id": 2,
            "event_id": 2,
            "published_time": "2026-09-08 18:00:00",
            "participant_count": 4,
            "reaction_count": 5,
        },
        {
            "id": 3,
            "event_id": 3,
            "published_time": "2026-09-07 18:00:00",
            "participant_count": 1,
            "reaction_count": 2,
        },
    ]

    archive = _group_event_effects_by_week_day(rows)

    assert list(archive) == [date(2026, 9, 7), date(2026, 8, 31)]
    assert list(archive[date(2026, 9, 7)]) == [date(2026, 9, 8), date(2026, 9, 7)]
    assert [row["event_id"] for row in archive[date(2026, 9, 7)][date(2026, 9, 8)]] == [2]


def test_event_archive_labels_surface_week_day_and_activity_metrics() -> None:
    rows = [
        {
            "event_id": 1,
            "participant_count": 2,
            "reaction_count": 3,
        },
        {
            "event_id": 2,
            "participant_count": 4,
            "reaction_count": 5,
        },
    ]

    assert _event_week_archive_label(date(2026, 9, 7), rows) == (
        "2026 年第 37 周 · 09/07–09/13 · 2 个活动"
    )
    assert _event_day_archive_label(date(2026, 9, 8), rows) == (
        "09 月 08 日 · 2 个活动 · 参与 6 · 互动 8"
    )
