from __future__ import annotations

from pathlib import Path

from app.bot.command_service import BotCommandService
from app.bot.event_publisher import InMemoryEventPublisher, should_use_native_poll
from app.database.migrations.init_db import init_database
from app.database.repositories.event_repository import EventRepository
from app.scheduler.event_jobs import EventPublishService
from app.scheduler.event_options import (
    format_option_winner,
    format_event_content,
    map_poll_results_to_options,
    options_from_json,
    options_to_json,
    poll_results_to_json,
    parse_event_options,
)
from app.utils.time_utils import parse_datetime


def test_event_options_parse_json_and_format_content() -> None:
    options = parse_event_options("Arena\nDungeon, Raid")
    options_json = options_to_json(options)

    assert options == ["Arena", "Dungeon", "Raid"]
    assert options_from_json(options_json) == options
    assert format_event_content("Choose one.", "Poll", options_json) == (
        "Choose one.\n\n"
        "Options:\n"
        "A. Arena\n"
        "B. Dungeon\n"
        "C. Raid\n\n"
        "React with the matching option letter to vote."
    )


def test_command_service_saves_event_options(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    BotCommandService(db_path).schedule_event(
        title="Weekly Poll",
        content="Pick one mode.",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        options="Arena,Dungeon",
    )

    event = EventRepository(db_path).list_recent(1)[0]
    assert options_from_json(event["event_options_json"]) == ["Arena", "Dungeon"]


def test_event_publish_service_sends_formatted_options(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    EventRepository(db_path).create(
        title="Weekly Poll",
        content="Pick one mode.",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        repeat_rule="none",
        status="Scheduled",
        event_options_json=options_to_json(["Arena", "Dungeon"]),
    )

    publisher = InMemoryEventPublisher()
    EventPublishService(publisher, db_path).publish_due_events(
        now=parse_datetime("2026-07-31 18:00:01")
    )

    assert publisher.published_messages[0]["content"] == "Pick one mode."
    assert publisher.published_messages[0]["uses_native_poll"] == "True"
    assert publisher.published_messages[0]["event_options_json"] == options_to_json(
        ["Arena", "Dungeon"]
    )


def test_native_poll_is_used_only_for_poll_events_with_options() -> None:
    options_json = options_to_json(["Arena", "Dungeon"])

    assert should_use_native_poll("Poll", options_json) is True
    assert should_use_native_poll("Survey", options_json) is False
    assert should_use_native_poll("Poll", None) is False


def test_poll_results_are_mapped_to_option_labels() -> None:
    options_json = options_to_json(["Arena", "Dungeon"])
    mapped = map_poll_results_to_options({"A": 2, "🇧": 3, "other": 1}, options_json)

    assert mapped["raw_reactions"] == {"A": 2, "🇧": 3, "other": 1}
    assert mapped["option_results"] == [
        {"marker": "A", "option": "Arena", "count": 2},
        {"marker": "B", "option": "Dungeon", "count": 3},
    ]
    assert format_option_winner(poll_results_to_json({"A": 2, "🇧": 3}, options_json)) == (
        "B. Dungeon (3 votes)"
    )
