from __future__ import annotations

from pathlib import Path

from app.bot.event_analytics_collector import EventMetrics, InMemoryEventAnalyticsCollector
from app.database.migrations.init_db import init_database
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.scheduler.analytics_jobs import EventAnalyticsService


def test_event_analytics_service_updates_latest_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    events = EventRepository(db_path)
    event_id = events.create(
        title="Weekly Poll",
        content="Pick one mode.",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        repeat_rule="none",
        status="Scheduled",
    )
    events.update_status(event_id, "Published", "discord-message-1")
    analytics = EventAnalyticsRepository(db_path)
    analytics_id = analytics.create_initial(event_id, "2026-07-31 18:00:00")

    collector = InMemoryEventAnalyticsCollector(
        {
            "discord-message-1": EventMetrics(
                participant_count=3,
                reaction_count=5,
                poll_result={"A": 2, "B": 3},
            )
        }
    )

    results = EventAnalyticsService(collector, db_path).update_all_published_event_metrics()

    assert len(results) == 1
    assert results[0].event_id == event_id
    assert results[0].analytics_id == analytics_id
    updated = analytics.list_by_event(event_id)[0]
    assert updated["participant_count"] == 3
    assert updated["reaction_count"] == 5
    assert '"raw_reactions": {"A": 2, "B": 3}' in updated["poll_result_json"]


def test_discord_poll_metrics_are_mapped_by_answer_order() -> None:
    from app.bot.event_analytics_collector import OPTION_MARKERS

    class Answer:
        def __init__(self, vote_count: int) -> None:
            self.vote_count = vote_count

    poll_results = {
        OPTION_MARKERS[index]: answer.vote_count
        for index, answer in enumerate([Answer(2), Answer(3)])
    }

    assert poll_results == {"A": 2, "B": 3}


def test_event_analytics_service_skips_events_without_initial_analytics(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    events = EventRepository(db_path)
    event_id = events.create(
        title="Announcement",
        content="Hello.",
        event_type="Announcement",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        repeat_rule="none",
        status="Scheduled",
    )
    events.update_status(event_id, "Published", "discord-message-1")

    results = EventAnalyticsService(
        InMemoryEventAnalyticsCollector(),
        db_path,
    ).update_all_published_event_metrics()

    assert results == []


def test_event_analytics_recent_join_includes_event_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    events = EventRepository(db_path)
    event_id = events.create(
        title="Quiz Night",
        content="Answer this.",
        event_type="Quiz",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        repeat_rule="none",
        status="Scheduled",
    )
    events.update_status(event_id, "Published", "discord-message-1")
    analytics = EventAnalyticsRepository(db_path)
    analytics.create_initial(event_id, "2026-07-31 18:00:00")

    row = analytics.list_recent_with_events(1)[0]

    assert row["title"] == "Quiz Night"
    assert row["event_type"] == "Quiz"
    assert row["discord_message_id"] == "discord-message-1"
