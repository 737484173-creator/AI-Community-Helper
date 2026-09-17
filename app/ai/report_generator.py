from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ai.ai_client import AIClient
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.scheduler.event_options import format_option_winner


@dataclass(frozen=True)
class ReportSummary:
    message_count: int
    ai_reply_count: int
    feedback_count: int
    high_priority_count: int
    pending_ticket_count: int
    open_pending_ticket_count: int
    message_type_counts: dict[str, int]
    feedback_category_counts: dict[str, int]
    sentiment_counts: dict[str, int]
    top_feedback_items: list[str]
    top_events: list[str]


class CommunityReportGenerator:
    def __init__(
        self,
        db_path: str | Path | None = None,
        ai_client: AIClient | None = None,
    ) -> None:
        self.messages = MessageRepository(db_path)
        self.feedback = FeedbackRepository(db_path)
        self.pending_tickets = PendingTicketRepository(db_path)
        self.event_analytics = EventAnalyticsRepository(db_path)
        self.ai_client = ai_client

    def build_summary(self, start_time: str, end_time: str) -> ReportSummary:
        return ReportSummary(
            message_count=self.messages.count_between(
                start_time,
                end_time,
                message_source="CHANNEL",
            ),
            ai_reply_count=self.messages.count_ai_replies_between(start_time, end_time),
            feedback_count=self.feedback.count_between(start_time, end_time),
            high_priority_count=self.feedback.count_high_priority_between(
                start_time,
                end_time,
            ),
            pending_ticket_count=self.pending_tickets.count_between(start_time, end_time),
            open_pending_ticket_count=self.pending_tickets.count_open(),
            message_type_counts=_rows_to_count_dict(
                self.messages.count_by_type_between(
                    start_time,
                    end_time,
                    message_source="CHANNEL",
                ),
                "message_type",
            ),
            feedback_category_counts=_rows_to_count_dict(
                self.feedback.count_by_category_between(start_time, end_time),
                "category",
            ),
            sentiment_counts=_rows_to_count_dict(
                self.feedback.count_by_sentiment_between(start_time, end_time),
                "sentiment",
            ),
            top_feedback_items=[
                _format_feedback_item(row) for row in self.feedback.list_top_open(5)
            ],
            top_events=[
                _format_event_item(row)
                for row in self.event_analytics.list_between_with_events(
                    start_time,
                    end_time,
                    5,
                )
            ],
        )

    def generate_report(
        self,
        report_type: str,
        start_time: str,
        end_time: str,
    ) -> str:
        summary = self.build_summary(start_time, end_time)
        draft = _render_report(report_type, start_time, end_time, summary)
        if self.ai_client is None:
            return draft

        return self.ai_client.generate(
            system_prompt=(
                "You are an AI community operations analyst. Rewrite the provided "
                "operations report using only the supplied metrics and facts. "
                "Do not invent player account, VIP, revenue, or identity data."
            ),
            user_prompt=draft,
        )


def _rows_to_count_dict(rows, key: str) -> dict[str, int]:
    return {str(row[key]): int(row["total"]) for row in rows}


def _format_feedback_item(row) -> str:
    feature = row["feature"] or "General"
    return (
        f"{row['priority']} | {row['category']} | {feature} | "
        f"{row['sentiment']} | {row['content']}"
    )


def _format_event_item(row) -> str:
    base = (
        f"{row['title']} ({row['event_type']}): "
        f"{row['participant_count']} participants, {row['reaction_count']} reactions"
    )
    winner = format_option_winner(row["poll_result_json"])
    if winner:
        return f"{base}, winner: {winner}"
    return base


def _render_report(
    report_type: str,
    start_time: str,
    end_time: str,
    summary: ReportSummary,
) -> str:
    return "\n".join(
        [
            f"# {report_type} Community Report",
            "",
            f"Period: {start_time} to {end_time}",
            "",
            "## Key Metrics",
            f"- Messages: {summary.message_count}",
            f"- AI replies: {summary.ai_reply_count}",
            f"- Feedback items: {summary.feedback_count}",
            f"- High priority feedback: {summary.high_priority_count}",
            f"- New pending tickets: {summary.pending_ticket_count}",
            f"- Open pending tickets: {summary.open_pending_ticket_count}",
            "",
            "## Message Types",
            _format_count_section(summary.message_type_counts),
            "",
            "## Feedback Categories",
            _format_count_section(summary.feedback_category_counts),
            "",
            "## Sentiment",
            _format_count_section(summary.sentiment_counts),
            "",
            "## Top Feedback",
            _format_list_section(summary.top_feedback_items),
            "",
            "## Event Performance",
            _format_list_section(summary.top_events),
            "",
            "## Suggested Actions",
            *_suggest_actions(summary),
        ]
    )


def _format_count_section(values: dict[str, int]) -> str:
    if not values:
        return "- No data"
    return "\n".join(f"- {key}: {value}" for key, value in values.items())


def _format_list_section(values: list[str]) -> str:
    if not values:
        return "- No data"
    return "\n".join(f"- {value}" for value in values)


def _suggest_actions(summary: ReportSummary) -> list[str]:
    actions: list[str] = []
    if summary.high_priority_count:
        actions.append("- Review high priority feedback before the next community update.")
    if summary.open_pending_ticket_count:
        actions.append("- Assign open pending tickets to human operators.")
    if summary.feedback_category_counts.get("REWARD_ISSUE", 0) > 0:
        actions.append("- Review reward-related complaints and compare them with event design.")
    if summary.feedback_category_counts.get("BUG", 0) > 0:
        actions.append("- Share top BUG feedback with QA or the development team.")
    if not actions:
        actions.append("- Continue monitoring FAQ coverage and player sentiment.")
    return actions
