from __future__ import annotations

from pathlib import Path

from app.database.db import db_session, get_db_path
from app.database.models import SCHEMA_SQL


def init_database(db_path: str | Path | None = None) -> Path:
    target_path = Path(db_path) if db_path else get_db_path()
    with db_session(target_path) as connection:
        connection.executescript(SCHEMA_SQL)
        _apply_lightweight_migrations(connection)
    return target_path


def _apply_lightweight_migrations(connection) -> None:
    user_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    if "discord_user_name" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN discord_user_name TEXT")
    connection.execute(
        """
        UPDATE users
        SET discord_user_name = (
            SELECT feedback.discord_user_name
            FROM feedback
            WHERE feedback.discord_user_id = users.discord_user_id
              AND TRIM(COALESCE(feedback.discord_user_name, '')) != ''
            ORDER BY feedback.updated_time DESC, feedback.id DESC
            LIMIT 1
        )
        WHERE TRIM(COALESCE(discord_user_name, '')) = ''
          AND EXISTS (
            SELECT 1
            FROM feedback
            WHERE feedback.discord_user_id = users.discord_user_id
              AND TRIM(COALESCE(feedback.discord_user_name, '')) != ''
          )
        """
    )

    message_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
    }
    if "message_source" not in message_columns:
        connection.execute(
            "ALTER TABLE messages ADD COLUMN message_source TEXT NOT NULL DEFAULT 'CHANNEL'"
        )
    if "discord_message_id" not in message_columns:
        connection.execute("ALTER TABLE messages ADD COLUMN discord_message_id TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_discord_message_id "
            "ON messages(discord_message_id)"
        )

    feedback_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(feedback)").fetchall()
    }
    if "keywords" not in feedback_columns:
        connection.execute("ALTER TABLE feedback ADD COLUMN keywords TEXT")
    if "channel_id" not in feedback_columns:
        connection.execute("ALTER TABLE feedback ADD COLUMN channel_id TEXT")
    if "channel_name" not in feedback_columns:
        connection.execute("ALTER TABLE feedback ADD COLUMN channel_name TEXT")
    if "discord_user_name" not in feedback_columns:
        connection.execute("ALTER TABLE feedback ADD COLUMN discord_user_name TEXT")
    if "thread_title" not in feedback_columns:
        connection.execute("ALTER TABLE feedback ADD COLUMN thread_title TEXT")
    connection.execute(
        """
        UPDATE feedback
        SET channel_id = (
            SELECT messages.channel_id
            FROM messages
            WHERE messages.discord_user_id = feedback.discord_user_id
              AND messages.message = feedback.content
            ORDER BY messages.created_time DESC
            LIMIT 1
        )
        WHERE channel_id IS NULL
          AND EXISTS (
            SELECT 1
            FROM messages
            WHERE messages.discord_user_id = feedback.discord_user_id
              AND messages.message = feedback.content
          )
        """
    )
    connection.execute(
        """
        UPDATE feedback
        SET thread_title = (
                SELECT discord_channels.channel_name
                FROM discord_channels
                WHERE discord_channels.channel_id = feedback.channel_id
                  AND discord_channels.channel_type = 'Thread'
            ),
            channel_name = CASE
                WHEN channel_name IS NULL THEN 'bug-report'
                ELSE channel_name
            END
        WHERE channel_id IN (
            SELECT channel_id
            FROM discord_channels
            WHERE channel_type = 'Thread'
        )
          AND thread_title IS NULL
        """
    )

    ticket_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(pending_tickets)").fetchall()
    }
    if "ticket_source" not in ticket_columns:
        connection.execute(
            "ALTER TABLE pending_tickets "
            "ADD COLUMN ticket_source TEXT NOT NULL DEFAULT 'AI_DM_UNRESOLVED'"
        )
    connection.execute(
        """
        UPDATE pending_tickets
        SET ticket_source = 'COMMAND_TICKET'
        WHERE issue_description = 'Created from /ticket command.'
        """
    )
    connection.execute(
        """
        UPDATE pending_tickets
        SET ticket_source = 'FAQ_FLOW_UNRESOLVED'
        WHERE issue_description != 'No confident FAQ match was found.'
          AND ticket_source = 'AI_DM_UNRESOLVED'
        """
    )
    connection.execute(
        """
        UPDATE pending_tickets
        SET ticket_source = 'FAQ_FLOW_UNRESOLVED'
        WHERE ticket_source = 'AI_DM_UNRESOLVED'
          AND (selected_category IS NOT NULL OR selected_question IS NOT NULL)
        """
    )

    event_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(events)").fetchall()
    }
    if "event_options_json" not in event_columns:
        connection.execute("ALTER TABLE events ADD COLUMN event_options_json TEXT")
    if "event_image_path" not in event_columns:
        connection.execute("ALTER TABLE events ADD COLUMN event_image_path TEXT")

    vip_snapshot_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(vip_ae_snapshots)").fetchall()
    }
    if "payment_previous_7d_amount" not in vip_snapshot_columns:
        connection.execute(
            "ALTER TABLE vip_ae_snapshots ADD COLUMN payment_previous_7d_amount REAL"
        )
    if "payment_28d_weekly_avg" not in vip_snapshot_columns:
        connection.execute(
            "ALTER TABLE vip_ae_snapshots ADD COLUMN payment_28d_weekly_avg REAL"
        )

    vip_sync_run_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(vip_ae_sync_runs)").fetchall()
    }
    if "previous_week_window" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs ADD COLUMN previous_week_window TEXT"
        )
    if "rolling_28d_window" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs ADD COLUMN rolling_28d_window TEXT"
        )


if __name__ == "__main__":
    database_path = init_database()
    print(f"Database initialized: {database_path}")
