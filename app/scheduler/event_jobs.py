from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.bot.event_publisher import EventPublisher
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.event_assets import resolve_event_image_path
from app.scheduler.event_options import format_event_content
from app.scheduler.repeat_rules import calculate_next_publish_time
from app.utils.time_utils import format_datetime, parse_datetime


@dataclass(frozen=True)
class EventPublishResult:
    event_id: int
    discord_message_id: str
    analytics_id: int
    next_publish_time: str | None


class EventPublishService:
    def __init__(
        self,
        publisher: EventPublisher,
        db_path: str | Path | None = None,
    ) -> None:
        self.publisher = publisher
        self.events = EventRepository(db_path)
        self.analytics = EventAnalyticsRepository(db_path)

    def publish_due_events(self, now: datetime | None = None) -> list[EventPublishResult]:
        current_time = now or datetime.now()
        due_events = self.events.list_due(format_datetime(current_time))
        results: list[EventPublishResult] = []

        for event in due_events:
            publish_time = parse_datetime(str(event["publish_time"]))
            image_path = resolve_event_image_path(self.events.db_path, event["event_image_path"])
            if image_path is not None and not image_path.is_file():
                raise FileNotFoundError(f"Activity image is missing: {image_path}")
            discord_message_id = self.publisher.publish(
                channel_id=str(event["channel_id"]),
                title=str(event["title"]),
                content=_publish_content_for_event(event),
                event_type=str(event["event_type"]),
                event_options_json=event["event_options_json"],
                image_path=str(image_path) if image_path is not None else None,
            )
            analytics_id = self.analytics.create_initial(
                event_id=int(event["id"]),
                published_time=format_datetime(current_time),
            )
            next_publish_time = calculate_next_publish_time(
                publish_time=publish_time,
                repeat_rule=str(event["repeat_rule"]),
            )

            if next_publish_time:
                next_time_text = format_datetime(next_publish_time)
                self.events.reschedule(
                    event_id=int(event["id"]),
                    next_publish_time=next_time_text,
                    discord_message_id=discord_message_id,
                )
            else:
                next_time_text = None
                self.events.update_status(
                    event_id=int(event["id"]),
                    status="Published",
                    discord_message_id=discord_message_id,
                )

            results.append(
                EventPublishResult(
                    event_id=int(event["id"]),
                    discord_message_id=discord_message_id,
                    analytics_id=analytics_id,
                    next_publish_time=next_time_text,
                )
            )

        return results


def _publish_content_for_event(event) -> str:
    event_type = str(event["event_type"])
    if event_type == "Poll" and event["event_options_json"]:
        return str(event["content"])
    return format_event_content(
        content=str(event["content"]),
        event_type=event_type,
        event_options_json=event["event_options_json"],
    )
