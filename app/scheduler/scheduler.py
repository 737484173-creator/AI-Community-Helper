from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.bot.event_analytics_collector import EventAnalyticsCollector
from app.bot.event_publisher import EventPublisher
from app.scheduler.analytics_jobs import EventAnalyticsService
from app.scheduler.event_jobs import EventPublishService
from app.scheduler.report_jobs import ReportJobService


logger = logging.getLogger(__name__)


def create_scheduler(
    event_publisher: EventPublisher,
    analytics_collector: EventAnalyticsCollector | None = None,
    db_path: str | None = None,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    event_service = EventPublishService(event_publisher, db_path)

    scheduler.add_job(
        func=lambda: _publish_due_events(event_service),
        trigger="interval",
        seconds=30,
        id="publish_due_events",
        replace_existing=True,
    )

    if analytics_collector is not None:
        analytics_service = EventAnalyticsService(analytics_collector, db_path)
        scheduler.add_job(
            func=lambda: _update_event_analytics(analytics_service),
            trigger="interval",
            seconds=60,
            id="update_event_analytics",
            replace_existing=True,
        )

    report_service = ReportJobService(db_path)
    scheduler.add_job(
        func=report_service.generate_daily_report,
        trigger="cron",
        hour=0,
        minute=5,
        id="generate_daily_report",
        replace_existing=True,
    )
    scheduler.add_job(
        func=report_service.generate_weekly_report,
        trigger="cron",
        day_of_week="mon",
        hour=0,
        minute=8,
        id="generate_weekly_report",
        replace_existing=True,
    )
    return scheduler


def _publish_due_events(event_service: EventPublishService) -> None:
    results = event_service.publish_due_events()
    if results:
        logger.info("Published %s due community event(s).", len(results))


def _update_event_analytics(analytics_service: EventAnalyticsService) -> None:
    results = analytics_service.update_all_published_event_metrics()
    if results:
        logger.info("Updated analytics for %s community event(s).", len(results))
