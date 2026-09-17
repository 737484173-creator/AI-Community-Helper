from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.bot.content_moderation import MONITORED_CHANNEL_NAMES, public_message_risk_level
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.utils.time_utils import format_datetime


AI_DM_UNRESOLVED_SOURCE = "AI_DM_UNRESOLVED"


@dataclass(frozen=True)
class DashboardMetrics:
    today_messages: int
    today_ai_replies: int
    today_feedback: int
    today_high_risk_messages: int
    open_pending_tickets: int


class DashboardDataService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.messages = MessageRepository(db_path)
        self.feedback = FeedbackRepository(db_path)
        self.pending_tickets = PendingTicketRepository(db_path)
        self.event_analytics = EventAnalyticsRepository(db_path)

    def get_today_metrics(self, now: datetime | None = None) -> DashboardMetrics:
        current_time = now or datetime.now()
        start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        end = current_time.replace(hour=23, minute=59, second=59, microsecond=0)
        start_text = format_datetime(start)
        end_text = format_datetime(end)

        monitored_rows = self.messages.list_channels_messages_between(
            start_text,
            end_text,
            tuple(sorted(MONITORED_CHANNEL_NAMES)),
            limit=10_000,
        )
        return DashboardMetrics(
            today_messages=self.messages.count_between(
                start_text,
                end_text,
                message_source="CHANNEL",
            ),
            today_ai_replies=self.messages.count_ai_replies_between(start_text, end_text),
            today_feedback=self.feedback.count_between(start_text, end_text),
            today_high_risk_messages=sum(
                1
                for row in monitored_rows
                if public_message_risk_level(str(row["message"] or "")) == "高风险"
            ),
            open_pending_tickets=self.pending_tickets.count_open(AI_DM_UNRESOLVED_SOURCE),
        )

    def get_today_sentiment_counts(self, now: datetime | None = None) -> dict[str, int]:
        current_time = now or datetime.now()
        start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        end = current_time.replace(hour=23, minute=59, second=59, microsecond=0)
        rows = self.feedback.count_by_sentiment_between(
            format_datetime(start),
            format_datetime(end),
        )
        return {str(row["sentiment"]): int(row["total"]) for row in rows}

    def get_today_feedback_categories(self, now: datetime | None = None) -> dict[str, int]:
        current_time = now or datetime.now()
        start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        end = current_time.replace(hour=23, minute=59, second=59, microsecond=0)
        rows = self.feedback.count_by_category_between(
            format_datetime(start),
            format_datetime(end),
        )
        return {str(row["category"]): int(row["total"]) for row in rows}
