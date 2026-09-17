from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from app.database.migrations.init_db import init_database
from app.ai.event_retrospective import EventRetrospectiveService
from app.bot.history_backfill import run_history_backfill
from app.scheduler.report_jobs import ReportJobService
from app.utils.time_utils import parse_datetime
from app.utils.excel_importer import import_faq_from_excel
from app.vip.ae_sync import (
    AEVIPSyncError,
    AEVIPSyncService,
    DEFAULT_AE_PROJECT_ID,
    DEFAULT_MINIMUM_PAYMENT_USD,
)
from config.settings import get_settings


BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Community Operation Center manager.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize or migrate SQLite database.")

    import_faq = subparsers.add_parser("import-faq", help="Import FAQ Excel workbook.")
    import_faq.add_argument("excel_path", help="Path to SDK.xlsx or another FAQ workbook.")
    import_faq.add_argument("--db-path", help="Optional SQLite database path.")

    dashboard = subparsers.add_parser("dashboard", help="Run Streamlit dashboard.")
    dashboard.add_argument("--port", default="8502", help="Dashboard port.")

    subparsers.add_parser("bot", help="Run Discord bot.")

    backfill = subparsers.add_parser(
        "backfill-discord",
        help="Backfill all readable user messages from Discord channel history.",
    )
    backfill.add_argument(
        "--since",
        help="Optional local start date/time, for example 2026-07-30 or 2026-07-30T00:00:00.",
    )
    backfill.add_argument(
        "--skip-report-refresh",
        action="store_true",
        help="Do not refresh saved daily and weekly report snapshots after import.",
    )

    report = subparsers.add_parser("report", help="Generate a community report.")
    report.add_argument("report_type", choices=("daily", "weekly", "custom"))
    report.add_argument("--start", help="Custom report start time: YYYY-MM-DD HH:MM:SS")
    report.add_argument("--end", help="Custom report end time: YYYY-MM-DD HH:MM:SS")
    report.add_argument("--db-path", help="Optional SQLite database path.")

    retrospective = subparsers.add_parser(
        "event-retrospective",
        help="Generate an event retrospective report.",
    )
    retrospective.add_argument("event_id", type=int)
    retrospective.add_argument("--db-path", help="Optional SQLite database path.")

    sync_ae_vip = subparsers.add_parser(
        "sync-ae-vip",
        help="Sync AE project VIP data into the local workbench snapshot.",
    )
    sync_ae_vip.add_argument(
        "--project-id",
        type=int,
        default=DEFAULT_AE_PROJECT_ID,
        help=f"AE project ID (default: {DEFAULT_AE_PROJECT_ID}).",
    )
    sync_ae_vip.add_argument(
        "--minimum-payment",
        type=float,
        default=DEFAULT_MINIMUM_PAYMENT_USD,
        help=f"Minimum cumulative USD payment (default: {DEFAULT_MINIMUM_PAYMENT_USD:g}).",
    )
    sync_ae_vip.add_argument("--db-path", help="Optional SQLite database path.")

    args = parser.parse_args()
    if args.command == "init-db":
        database_path = init_database()
        print(f"Database initialized: {database_path}")
    elif args.command == "import-faq":
        result = import_faq_from_excel(args.excel_path, args.db_path)
        print(
            "FAQ import completed: "
            f"imported={result.imported_count}, "
            f"skipped={result.skipped_count}, "
            f"categories={', '.join(result.categories)}"
        )
    elif args.command == "dashboard":
        _run_dashboard(args.port)
    elif args.command == "bot":
        from app.bot.discord_bot import run_bot

        run_bot()
    elif args.command == "backfill-discord":
        settings = get_settings()
        if not settings.discord_bot_token:
            raise SystemExit("DISCORD_BOT_TOKEN is required for history backfill.")
        init_database(settings.db_path)
        result = run_history_backfill(
            token=settings.discord_bot_token,
            db_path=settings.db_path,
            proxy=settings.discord_proxy,
            since=args.since,
        )
        refreshed_reports = 0
        if not args.skip_report_refresh:
            refreshed_reports = ReportJobService(settings.db_path).refresh_existing_reports()
        print(
            "Discord history backfill completed: "
            f"guilds={result.guilds_scanned}, "
            f"channels={result.channels_scanned}, "
            f"seen={result.messages_seen}, "
            f"inserted={result.messages_inserted}, "
            f"existing={result.messages_existing}, "
            f"skipped={result.messages_skipped}, "
            f"warnings={len(result.warnings)}, "
            f"reports_refreshed={refreshed_reports}"
        )
        for warning in result.warnings:
            print(f"Warning: {warning}")
    elif args.command == "report":
        init_database(args.db_path)
        service = ReportJobService(args.db_path)
        if args.report_type == "daily":
            generated = service.generate_daily_report()
        elif args.report_type == "weekly":
            generated = service.generate_weekly_report()
        else:
            if not args.start or not args.end:
                raise SystemExit("Custom reports require --start and --end.")
            generated = service.generate_custom_report(
                parse_datetime(args.start),
                parse_datetime(args.end),
            )
        print(
            f"Generated {generated.report_type} report #{generated.report_id}: "
            f"{generated.start_time} to {generated.end_time}"
        )
    elif args.command == "event-retrospective":
        init_database(args.db_path)
        try:
            report_id = EventRetrospectiveService(args.db_path).generate_for_event(args.event_id)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Generated event retrospective report #{report_id} for event #{args.event_id}")
    elif args.command == "sync-ae-vip":
        try:
            result = AEVIPSyncService(
                args.db_path,
                project_id=args.project_id,
                minimum_payment_usd=args.minimum_payment,
            ).sync()
        except AEVIPSyncError as exc:
            raise SystemExit(f"AE VIP sync failed: {exc}") from exc
        print(
            "AE VIP sync completed: "
            f"project_id={result.project_id}, "
            f"source_rows={result.source_row_count}, "
            f"vip_rows={result.vip_row_count}, "
            f"cumulative_window={result.cumulative_window}, "
            f"weekly_window={result.weekly_window}, "
            f"synced_at={result.synced_at}"
        )


def _run_dashboard(port: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(BASE_DIR / "app" / "dashboard" / "streamlit_app.py"),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--server.runOnSave",
            "true",
            "--server.fileWatcherType",
            "poll",
            "--browser.gatherUsageStats",
            "false",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
