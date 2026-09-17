from __future__ import annotations

from datetime import date
from pathlib import Path

from app.dashboard.export_utils import (
    records_to_csv,
    safe_download_filename,
    text_to_markdown_bytes,
)
from app.dashboard.views.reports import (
    _activity_date_range,
    _count_items,
    _daily_message_activity,
    _group_reports_by_year_month,
    _group_reports_by_week,
    _key_metrics,
    _month_archive_label,
    _report_archive_page,
    _report_period,
    _report_title,
    _week_archive_label,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.report_repository import ReportRepository


def test_report_repository_get_by_id(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = ReportRepository(db_path)
    report_id = repository.create(
        report_type="Daily",
        title="Daily Community Report",
        content="# Daily Community Report",
        start_time="2026-07-31 00:00:00",
        end_time="2026-07-31 23:59:59",
    )

    report = repository.get_by_id(report_id)

    assert report is not None
    assert report["title"] == "Daily Community Report"


def test_report_export_helpers() -> None:
    markdown = text_to_markdown_bytes("# Report")
    filename = safe_download_filename("Daily Community Report 2026/07/31", "md")
    csv_bytes = records_to_csv([{"id": 1, "title": "Daily"}])

    assert markdown == b"# Report"
    assert filename == "Daily_Community_Report_2026_07_31.md"
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    assert b"Daily" in csv_bytes


def test_report_dashboard_extracts_structured_preview_sections() -> None:
    content = "\n".join(
        [
            "# Daily Community Report",
            "",
            "Period: 2026-08-06 00:00:00 to 2026-08-06 23:59:59",
            "",
            "## Key Metrics",
            "- Messages: 97",
            "- AI replies: 14",
            "",
            "## Message Types",
            "- OTHER: 83",
            "- FAQ: 10",
        ]
    )

    assert _report_title(content, "Fallback") == "Daily Community Report"
    assert _report_period(content, "start", "end") == (
        "2026-08-06 00:00:00 to 2026-08-06 23:59:59"
    )
    assert _key_metrics(content) == [("消息数", "97"), ("AI 回复", "14")]
    assert _count_items(content, "Message Types") == [("OTHER", 83), ("FAQ", 10)]


def test_report_archive_groups_year_then_month_in_descending_order() -> None:
    reports = [
        {"id": 1, "start_time": "2025-12-31 00:00:00"},
        {"id": 2, "start_time": "2026-08-01 00:00:00"},
        {"id": 3, "start_time": "2026-09-01 00:00:00"},
        {"id": 4, "start_time": "2026-08-31 00:00:00"},
    ]

    archive = _group_reports_by_year_month(reports)

    assert list(archive) == [2026, 2025]
    assert list(archive[2026]) == [9, 8]
    assert [record["id"] for record in archive[2026][8]] == [4, 2]


def test_month_archive_label_makes_report_count_unambiguous() -> None:
    reports = [
        *[{"report_type": "Daily"} for _ in range(7)],
        *[{"report_type": "Weekly"} for _ in range(2)],
    ]

    assert _month_archive_label(8, reports) == (
        "08 月归档 · 共 9 份报告 · 日报 7 · 周报 2"
    )


def test_report_archive_groups_by_monday_to_sunday_week() -> None:
    reports = [
        {"id": 1, "start_time": "2026-09-06 00:00:00", "report_type": "Daily"},
        {"id": 2, "start_time": "2026-09-07 00:00:00", "report_type": "Daily"},
        {"id": 3, "start_time": "2026-09-10 00:00:00", "report_type": "Weekly"},
    ]

    grouped = _group_reports_by_week(reports)

    assert [(start.isoformat(), end.isoformat()) for start, end, _ in grouped] == [
        ("2026-09-07", "2026-09-13"),
        ("2026-08-31", "2026-09-06"),
    ]
    assert [record["id"] for record in grouped[0][2]] == [3, 2]
    assert _week_archive_label(*grouped[0]) == (
        "09/07–09/13 · 第 37 周 · 共 2 份报告 · 周报 1 · 日报 1"
    )


def test_activity_date_range_is_inclusive() -> None:
    today = date(2026, 9, 7)

    assert _activity_date_range("近7天", today) == (
        date(2026, 9, 1),
        date(2026, 9, 7),
    )
    assert _activity_date_range(
        "自定义",
        today,
        date(2026, 8, 1),
        date(2026, 8, 31),
    ) == (date(2026, 8, 1), date(2026, 8, 31))


def test_daily_message_activity_fills_missing_days_with_zero() -> None:
    daily = _daily_message_activity(
        [
            {"message_date": "2026-09-01", "total": 3},
            {"message_date": "2026-09-03", "total": 5},
        ],
        date(2026, 9, 1),
        date(2026, 9, 3),
    )

    assert daily["完整日期"].tolist() == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert daily["消息数"].tolist() == [3, 0, 5]


def test_report_archive_page_only_returns_visible_slice() -> None:
    records = [{"id": value} for value in range(1, 20)]

    first_page, page_count, safe_page = _report_archive_page(records, 1)
    final_page, _, clamped_page = _report_archive_page(records, 99)

    assert [record["id"] for record in first_page] == list(range(1, 9))
    assert page_count == 3
    assert safe_page == 1
    assert [record["id"] for record in final_page] == [17, 18, 19]
    assert clamped_page == 3
