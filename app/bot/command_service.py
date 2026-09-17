from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.bot.faq_flow import FAQFlowService
from app.database.repositories.event_repository import EventRepository
from app.scheduler.event_options import options_to_json, parse_event_options
from app.scheduler.report_jobs import ReportJobService


@dataclass(frozen=True)
class TicketCommandResult:
    ticket_id: int
    response: str


@dataclass(frozen=True)
class ReportCommandResult:
    report_id: int
    response: str


@dataclass(frozen=True)
class EventCommandResult:
    event_id: int
    response: str


class BotCommandService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.faq_flow = FAQFlowService(db_path)
        self.reports = ReportJobService(db_path)
        self.events = EventRepository(db_path)

    def create_ticket(
        self,
        discord_user_id: str,
        channel_id: str,
        issue: str,
        category: str | None = None,
    ) -> TicketCommandResult:
        ticket_id = self.faq_flow.create_pending_ticket(
            discord_user_id=discord_user_id,
            channel_id=channel_id,
            original_message=issue,
            ticket_source="COMMAND_TICKET",
            selected_category=category,
            issue_description="Created from /ticket command.",
        )
        return TicketCommandResult(
            ticket_id=ticket_id,
            response=f"Ticket #{ticket_id} created for manual support.",
        )

    def generate_report(self, report_type: str) -> ReportCommandResult:
        normalized = report_type.lower().strip()
        if normalized == "daily":
            result = self.reports.generate_daily_report()
        elif normalized == "weekly":
            result = self.reports.generate_weekly_report()
        else:
            raise ValueError("report_type must be daily or weekly.")

        return ReportCommandResult(
            report_id=result.report_id,
            response=(
                f"Generated {result.report_type} report #{result.report_id}: "
                f"{result.start_time} to {result.end_time}."
            ),
        )

    def schedule_event(
        self,
        title: str,
        content: str,
        event_type: str,
        channel_id: str,
        publish_time: str,
        repeat_rule: str = "none",
        options: str | None = None,
    ) -> EventCommandResult:
        event_id = self.events.create(
            title=title,
            content=content,
            event_type=event_type,
            channel_id=channel_id,
            publish_time=publish_time,
            repeat_rule=repeat_rule,
            status="Scheduled",
            event_options_json=options_to_json(parse_event_options(options)),
        )
        return EventCommandResult(
            event_id=event_id,
            response=f"Scheduled {event_type} event #{event_id}: {title}.",
        )
