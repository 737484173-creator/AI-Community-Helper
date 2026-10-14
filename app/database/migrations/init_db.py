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
    for column_name in (
        "build_fp",
        "tech_fp",
        "soldier_fp",
        "beast_fp",
        "hero_fp",
        "hiryu_fp",
        "com_fp",
        "leg_tech_fp",
        "cur_fp",
    ):
        if column_name not in vip_snapshot_columns:
            connection.execute(
                f"ALTER TABLE vip_ae_snapshots ADD COLUMN {column_name} REAL"
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
    if "purchase_source_row_count" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs "
            "ADD COLUMN purchase_source_row_count INTEGER NOT NULL DEFAULT 0"
        )
    if "purchase_vip_package_count" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs "
            "ADD COLUMN purchase_vip_package_count INTEGER NOT NULL DEFAULT 0"
        )
    if "purchase_lifetime_window" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs ADD COLUMN purchase_lifetime_window TEXT"
        )
    if "purchase_7d_window" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs ADD COLUMN purchase_7d_window TEXT"
        )
    if "purchase_14d_window" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs ADD COLUMN purchase_14d_window TEXT"
        )
    if "purchase_recent_window" not in vip_sync_run_columns:
        connection.execute(
            "ALTER TABLE vip_ae_sync_runs ADD COLUMN purchase_recent_window TEXT"
        )

    vip_purchase_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(vip_purchase_packages)").fetchall()
    }
    for column_name, definition in (
        ("payment_channel", "TEXT NOT NULL DEFAULT 'cash'"),
        ("currency_name", "TEXT NOT NULL DEFAULT '美元'"),
        ("source_event", "TEXT NOT NULL DEFAULT 'role_pay'"),
        ("is_demand_evidence", "INTEGER NOT NULL DEFAULT 1"),
    ):
        if column_name not in vip_purchase_columns:
            connection.execute(
                f"ALTER TABLE vip_purchase_packages ADD COLUMN {column_name} {definition}"
            )
    connection.execute(
        """
        UPDATE vip_purchase_packages
        SET category = '龙币充值', is_demand_evidence = 0
        WHERE source_event = 'role_pay'
          AND (
              LOWER(COALESCE(giftbox_name, '')) LIKE '%dragon coin%'
              OR items_json LIKE '%\"item_id\":\"20000064\"%'
          )
        """
    )
    verified_dragon_coin_tiers = {
        "931701": "龙币 × 6",
        "931702": "龙币 × 30",
        "931703": "龙币 × 98",
        "931704": "龙币 × 198",
        "931705": "龙币 × 328",
        "931706": "龙币 × 648",
        "931707": "龙币 × 1296",
        "931708": "龙币 × 1944",
        "931709": "龙币 × 2592",
        "931710": "龙币 × 2998",
        "931711": "龙币 × 6480",
        "931712": "龙币 × 12888",
        "931713": "龙币 × 19440",
        "931714": "龙币 × 25920",
        "931715": "龙币 × 29980",
    }
    for giftbox_id, giftbox_name in verified_dragon_coin_tiers.items():
        connection.execute(
            """
            UPDATE vip_purchase_packages
            SET giftbox_name = CASE
                    WHEN COALESCE(giftbox_name, '') IN ('', '未命名礼包')
                      OR LOWER(COALESCE(giftbox_name, '')) LIKE '%dragon coin%'
                      OR COALESCE(giftbox_name, '') LIKE '龙币%'
                    THEN ?
                    ELSE giftbox_name
                END,
                category = '龙币充值',
                is_demand_evidence = 0
            WHERE source_event = 'role_pay'
              AND (giftbox_id = ? OR giftbox_id LIKE ?)
            """,
            (giftbox_name, giftbox_id, f"{giftbox_id}::%"),
        )
    verified_giftbox_names = {
        "61": ("重工狂魔", "其他"),
        "90012": ("城建礼包", "建筑发展"),
        "90014": ("城建礼包", "建筑发展"),
        "90015": ("城建礼包", "建筑发展"),
        "2000002": ("装备升星礼包", "装备强化"),
        "2000004": ("装备升星礼包", "装备强化"),
        "2000005": ("装备升星礼包", "装备强化"),
        "2000302": ("装备强化礼包", "装备强化"),
        "2000304": ("装备强化礼包", "装备强化"),
        "2000305": ("装备强化礼包", "装备强化"),
        "251002": ("神兽魂石礼包", "神兽养成"),
        "251004": ("神兽魂石礼包", "神兽养成"),
        "251005": ("神兽魂石礼包", "神兽养成"),
        "283001": ("机甲锻造豪礼", "巨兽机甲"),
        "283003": ("机甲锻造豪礼", "巨兽机甲"),
        "283005": ("机甲锻造豪礼", "巨兽机甲"),
        "283301": ("养成自选豪礼", "其他"),
        "283303": ("养成自选豪礼", "其他"),
        "283305": ("养成自选豪礼", "其他"),
        "940902": ("深渊巨龙", "其他"),
        "941201": ("霜龙裂爪", "其他"),
        "941202": ("灵蛇赐福", "其他"),
        "941203": ("凤凰涅槃", "其他"),
        "941204": ("流光溢彩", "其他"),
        "941205": ("冰火之城", "其他"),
        "941206": ("月驰星海", "其他"),
    }
    for giftbox_id, (giftbox_name, category) in verified_giftbox_names.items():
        connection.execute(
            """
            UPDATE vip_purchase_packages
            SET giftbox_name = ?, category = ?
            WHERE source_event = 'role_pay'
              AND (giftbox_id = ? OR giftbox_id LIKE ?)
              AND COALESCE(giftbox_name, '') IN ('', '未命名礼包')
            """,
            (giftbox_name, category, giftbox_id, f"{giftbox_id}::%"),
        )


if __name__ == "__main__":
    database_path = init_database()
    print(f"Database initialized: {database_path}")
