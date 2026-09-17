from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.ai.ai_client import AIClient
from app.ai.report_generator import CommunityReportGenerator
from app.database.repositories.report_repository import ReportRepository
from app.utils.time_utils import format_datetime


@dataclass(frozen=True)
class ReportGenerationResult:
    report_id: int
    report_type: str
    title: str
    start_time: str
    end_time: str


class ReportJobService:
    def __init__(
        self,
        db_path: str | Path | None = None,
        ai_client: AIClient | None = None,
    ) -> None:
        self.generator = CommunityReportGenerator(db_path, ai_client)
        self.reports = ReportRepository(db_path)

    def generate_daily_report(self, now: datetime | None = None) -> ReportGenerationResult:
        current_time = now or datetime.now()
        end = current_time.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            seconds=1
        )
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.generate_report("Daily", start, end)

    def generate_weekly_report(self, now: datetime | None = None) -> ReportGenerationResult:
        current_time = now or datetime.now()
        current_week_start = (current_time - timedelta(days=current_time.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = current_week_start - timedelta(seconds=1)
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.generate_report("Weekly", start, end)

    def refresh_existing_reports(
        self,
        report_types: tuple[str, ...] = ("Daily", "Weekly"),
    ) -> int:
        refreshed = 0
        for report in self.reports.list_by_types(report_types):
            content = self.generator.generate_report(
                str(report["report_type"]),
                str(report["start_time"]),
                str(report["end_time"]),
            )
            self.reports.update_content(int(report["id"]), content)
            refreshed += 1
        return refreshed

    def generate_custom_report(
        self,
        start: datetime,
        end: datetime,
    ) -> ReportGenerationResult:
        return self.generate_report("Custom", start, end)

    def generate_report(
        self,
        report_type: str,
        start: datetime,
        end: datetime,
    ) -> ReportGenerationResult:
        if end < start:
            raise ValueError("Report end time must be greater than or equal to start time.")
        start_time = format_datetime(start)
        end_time = format_datetime(end)
        title = f"{report_type} Community Report {start.date()}"
        content = self.generator.generate_report(report_type, start_time, end_time)
        report_id = self.reports.create(
            report_type=report_type,
            title=title,
            content=content,
            start_time=start_time,
            end_time=end_time,
        )
        return ReportGenerationResult(
            report_id=report_id,
            report_type=report_type,
            title=title,
            start_time=start_time,
            end_time=end_time,
        )
