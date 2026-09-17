from __future__ import annotations

from pathlib import Path

from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.report_repository import ReportRepository
from app.scheduler.event_options import format_option_winner, options_from_json


class EventRetrospectiveService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.events = EventRepository(db_path)
        self.analytics = EventAnalyticsRepository(db_path)
        self.feedback = FeedbackRepository(db_path)
        self.reports = ReportRepository(db_path)

    def generate_for_event(self, event_id: int) -> int:
        event = self.events.get_by_id(event_id)
        if event is None:
            raise ValueError(f"Event not found: {event_id}")

        analytics = self.analytics.get_latest_by_event(event_id)
        content = self._render_retrospective(event, analytics)
        report_id = self.reports.create(
            report_type="EventRetrospective",
            title=f"Event Retrospective #{event_id} - {event['title']}",
            content=content,
            start_time=str(event["publish_time"]),
            end_time=str(analytics["updated_time"] if analytics else event["publish_time"]),
        )
        return report_id

    def _render_retrospective(self, event, analytics) -> str:
        options = options_from_json(event["event_options_json"])
        winner = format_option_winner(analytics["poll_result_json"] if analytics else None)
        feedback_items = self.feedback.list_between(
            start_time=str(event["publish_time"]),
            end_time=str(analytics["updated_time"] if analytics else event["publish_time"]),
            limit=5,
        )

        lines = [
            f"# Event Retrospective: {event['title']}",
            "",
            "## Event",
            f"- Event ID: {event['id']}",
            f"- Type: {event['event_type']}",
            f"- Status: {event['status']}",
            f"- Channel ID: {event['channel_id']}",
            f"- Publish Time: {event['publish_time']}",
            f"- Repeat Rule: {event['repeat_rule']}",
            "",
            "## Content",
            str(event["content"]),
            "",
            "## Options",
            _format_options(options),
            "",
            "## Performance",
            _format_performance(analytics, winner),
            "",
            "## Related Feedback",
            _format_feedback(feedback_items),
            "",
            "## Next Actions",
            *_next_actions(analytics, winner, feedback_items),
        ]
        return "\n".join(lines)


def _format_options(options: list[str]) -> str:
    if not options:
        return "- No configured options"
    return "\n".join(f"- {chr(ord('A') + index)}. {option}" for index, option in enumerate(options))


def _format_performance(analytics, winner: str | None) -> str:
    if analytics is None:
        return "- No analytics collected yet"
    lines = [
        f"- Participants: {analytics['participant_count']}",
        f"- Reactions: {analytics['reaction_count']}",
    ]
    if winner:
        lines.append(f"- Winning option: {winner}")
    else:
        lines.append("- Winning option: No mapped winner")
    return "\n".join(lines)


def _format_feedback(feedback_items) -> str:
    if not feedback_items:
        return "- No related feedback in the event window"
    return "\n".join(
        (
            f"- {row['priority']} | {row['category']} | "
            f"{row['sentiment']} | {row['content']}"
        )
        for row in feedback_items
    )


def _next_actions(analytics, winner: str | None, feedback_items) -> list[str]:
    actions: list[str] = []
    if analytics is None:
        actions.append("- Collect analytics after the Discord message receives reactions.")
    elif int(analytics["participant_count"]) == 0:
        actions.append("- Try a clearer call to action or a better posting time.")
    if winner:
        actions.append("- Consider using the winning option as the theme for the next event.")
    if feedback_items:
        actions.append("- Review related feedback before scheduling the next activity.")
    if not actions:
        actions.append("- Continue monitoring participation and feedback.")
    return actions

