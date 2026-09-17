from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.bot.event_analytics_collector import EventAnalyticsCollector, EventMetrics
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.scheduler.event_options import poll_results_to_json


@dataclass(frozen=True)
class EventAnalyticsUpdateResult:
    event_id: int
    analytics_id: int
    metrics: EventMetrics


class EventAnalyticsService:
    def __init__(
        self,
        collector: EventAnalyticsCollector,
        db_path: str | Path | None = None,
    ) -> None:
        self.collector = collector
        self.events = EventRepository(db_path)
        self.analytics = EventAnalyticsRepository(db_path)

    def update_all_published_event_metrics(self) -> list[EventAnalyticsUpdateResult]:
        results: list[EventAnalyticsUpdateResult] = []
        for event in self.events.list_published_with_discord_message():
            latest_analytics = self.analytics.get_latest_by_event(int(event["id"]))
            if latest_analytics is None:
                continue

            metrics = self.collector.collect(
                channel_id=str(event["channel_id"]),
                discord_message_id=str(event["discord_message_id"]),
            )
            self.analytics.update_metrics(
                analytics_id=int(latest_analytics["id"]),
                participant_count=metrics.participant_count,
                reaction_count=metrics.reaction_count,
                poll_result_json=poll_results_to_json(
                    metrics.poll_result,
                    event["event_options_json"],
                ),
            )
            results.append(
                EventAnalyticsUpdateResult(
                    event_id=int(event["id"]),
                    analytics_id=int(latest_analytics["id"]),
                    metrics=metrics,
                )
            )
        return results
