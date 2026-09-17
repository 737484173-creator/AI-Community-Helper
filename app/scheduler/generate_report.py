from __future__ import annotations

import argparse
from datetime import datetime

from app.database.migrations.init_db import init_database
from app.scheduler.report_jobs import ReportJobService


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate community operation report.")
    parser.add_argument(
        "report_type",
        choices=("daily", "weekly", "custom"),
        help="Report type to generate.",
    )
    parser.add_argument(
        "--now",
        help="Optional current datetime in YYYY-MM-DD HH:MM:SS format.",
    )
    parser.add_argument("--db-path", help="Optional SQLite database path.")
    parser.add_argument("--start", help="Custom report start time: YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end", help="Custom report end time: YYYY-MM-DD HH:MM:SS")
    args = parser.parse_args()

    init_database(args.db_path)
    now = datetime.strptime(args.now, "%Y-%m-%d %H:%M:%S") if args.now else None
    service = ReportJobService(args.db_path)

    if args.report_type == "daily":
        result = service.generate_daily_report(now)
    elif args.report_type == "weekly":
        result = service.generate_weekly_report(now)
    else:
        if not args.start or not args.end:
            raise SystemExit("Custom reports require --start and --end.")
        result = service.generate_custom_report(
            datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S"),
            datetime.strptime(args.end, "%Y-%m-%d %H:%M:%S"),
        )

    print(
        f"Generated {result.report_type} report #{result.report_id}: "
        f"{result.start_time} to {result.end_time}"
    )


if __name__ == "__main__":
    main()
