from __future__ import annotations

import sqlite3
from datetime import datetime

from app.database.db import db_session
from app.database.repositories.base_repository import BaseRepository
from app.utils.time_utils import format_datetime


class MessageRepository(BaseRepository):
    def create(
        self,
        discord_user_id: str,
        channel_id: str,
        message: str,
        ai_reply: str | None = None,
        message_type: str | None = None,
        message_source: str = "CHANNEL",
        discord_message_id: str | None = None,
        created_time: str | None = None,
    ) -> int:
        if discord_message_id:
            existing = self.get_by_discord_message_id(discord_message_id)
            if existing:
                if created_time:
                    self._execute(
                        "UPDATE messages SET created_time = ? WHERE discord_message_id = ?",
                        (created_time, discord_message_id),
                    )
                return int(existing["id"])

        stored_created_time = created_time or format_datetime(datetime.now())
        try:
            return self._execute(
                """
                INSERT INTO messages (
                    discord_message_id, discord_user_id, channel_id, message_source,
                    message, ai_reply, message_type, created_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discord_message_id,
                    discord_user_id,
                    channel_id,
                    message_source,
                    message,
                    ai_reply,
                    message_type,
                    stored_created_time,
                ),
            )
        except sqlite3.IntegrityError:
            if not discord_message_id:
                raise
            existing = self.get_by_discord_message_id(discord_message_id)
            if not existing:
                raise
            return int(existing["id"])

    def get_by_discord_message_id(self, discord_message_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT * FROM messages
            WHERE discord_message_id = ?
            """,
            (discord_message_id,),
        )

    def create_if_new(
        self,
        discord_user_id: str,
        channel_id: str,
        message: str,
        ai_reply: str | None = None,
        message_type: str | None = None,
        message_source: str = "CHANNEL",
        discord_message_id: str | None = None,
        created_time: str | None = None,
    ) -> tuple[int, bool]:
        if not discord_message_id:
            return (
                self.create(
                    discord_user_id=discord_user_id,
                    channel_id=channel_id,
                    message=message,
                    ai_reply=ai_reply,
                    message_type=message_type,
                    message_source=message_source,
                    created_time=created_time,
                ),
                True,
            )

        stored_created_time = created_time or format_datetime(datetime.now())
        with db_session(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO messages (
                    discord_message_id, discord_user_id, channel_id, message_source,
                    message, ai_reply, message_type, created_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discord_message_id,
                    discord_user_id,
                    channel_id,
                    message_source,
                    message,
                    ai_reply,
                    message_type,
                    stored_created_time,
                ),
            )
            if cursor.rowcount == 1:
                return int(cursor.lastrowid), True

            existing = connection.execute(
                """
                SELECT id FROM messages
                WHERE discord_message_id = ?
                """,
                (discord_message_id,),
            ).fetchone()
            if not existing:
                raise RuntimeError("Failed to load existing Discord message after dedupe.")
            if created_time:
                connection.execute(
                    "UPDATE messages SET created_time = ? WHERE discord_message_id = ?",
                    (created_time, discord_message_id),
                )
            return int(existing["id"]), False

    def update_ai_reply(self, message_id: int, ai_reply: str, message_type: str) -> None:
        self._execute(
            """
            UPDATE messages
            SET ai_reply = ?, message_type = ?
            WHERE id = ?
            """,
            (ai_reply, message_type, message_id),
        )

    def list_recent(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._fetch_all(
            "SELECT * FROM messages ORDER BY created_time DESC, id DESC LIMIT ?",
            (limit,),
        )

    def list_between(
        self,
        start_time: str,
        end_time: str,
        message_type: str | None = None,
        message_source: str | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        filters = ["created_time BETWEEN ? AND ?"]
        params: list[object] = [start_time, end_time]

        if message_type and message_type != "All":
            filters.append("message_type = ?")
            params.append(message_type)

        if message_source and message_source != "All":
            filters.append("message_source = ?")
            params.append(message_source)

        params.append(limit)
        return self._fetch_all(
            """
            SELECT * FROM messages
            WHERE """ + " AND ".join(filters) + """
            ORDER BY created_time DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        )

    def list_channel_messages_between(
        self,
        start_time: str,
        end_time: str,
        channel_name: str,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                messages.*,
                discord_channels.channel_name AS channel_name,
                discord_channels.guild_id AS guild_id,
                users.discord_user_name AS discord_user_name
            FROM messages
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = messages.channel_id
            LEFT JOIN users
                ON users.discord_user_id = messages.discord_user_id
            WHERE messages.created_time BETWEEN ? AND ?
              AND messages.message_source = 'CHANNEL'
              AND LOWER(COALESCE(discord_channels.channel_name, '')) = LOWER(?)
            ORDER BY messages.created_time DESC, messages.id DESC
            LIMIT ?
            """,
            (start_time, end_time, channel_name, limit),
        )

    def list_channels_messages_between(
        self,
        start_time: str,
        end_time: str,
        channel_names: tuple[str, ...],
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        normalized_names = tuple(
            channel_name.strip().lower()
            for channel_name in channel_names
            if channel_name.strip()
        )
        if not normalized_names:
            return []

        channel_filters: list[str] = []
        params: list[object] = [start_time, end_time]
        for channel_name in normalized_names:
            channel_filters.append(
                "("
                "LOWER(TRIM(COALESCE(discord_channels.channel_name, ''))) = ? "
                "OR LOWER(TRIM(COALESCE(discord_channels.channel_name, ''))) LIKE ? "
                "OR LOWER(TRIM(COALESCE(discord_channels.channel_name, ''))) LIKE ?"
                ")"
            )
            params.extend((channel_name, f"%│{channel_name}", f"%|{channel_name}"))
        params.append(limit)

        return self._fetch_all(
            """
            SELECT
                messages.*,
                discord_channels.channel_name AS channel_name,
                discord_channels.guild_id AS guild_id,
                users.discord_user_name AS discord_user_name
            FROM messages
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = messages.channel_id
            LEFT JOIN users
                ON users.discord_user_id = messages.discord_user_id
            WHERE messages.created_time BETWEEN ? AND ?
              AND messages.message_source = 'CHANNEL'
              AND (""" + " OR ".join(channel_filters) + """)
            ORDER BY messages.created_time DESC, messages.id DESC
            LIMIT ?
            """,
            tuple(params),
        )

    def count_between(
        self,
        start_time: str,
        end_time: str,
        message_source: str | None = None,
    ) -> int:
        filters = ["created_time BETWEEN ? AND ?"]
        params: list[object] = [start_time, end_time]
        if message_source and message_source != "All":
            filters.append("message_source = ?")
            params.append(message_source)
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM messages
            WHERE """ + " AND ".join(filters),
            tuple(params),
        )
        return int(row["total"] if row else 0)

    def count_channel_messages_by_day(
        self,
        start_time: str,
        end_time: str,
    ) -> list[sqlite3.Row]:
        """Return daily totals for user messages collected from Discord channels."""
        return self._fetch_all(
            """
            SELECT
                SUBSTR(created_time, 1, 10) AS message_date,
                COUNT(*) AS total
            FROM messages
            WHERE created_time BETWEEN ? AND ?
              AND message_source = 'CHANNEL'
            GROUP BY SUBSTR(created_time, 1, 10)
            ORDER BY message_date ASC
            """,
            (start_time, end_time),
        )

    def count_ai_replies_between(self, start_time: str, end_time: str) -> int:
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM messages
            WHERE created_time BETWEEN ? AND ?
              AND ai_reply IS NOT NULL
              AND ai_reply != ''
            """,
            (start_time, end_time),
        )
        return int(row["total"] if row else 0)

    def count_by_type_between(
        self,
        start_time: str,
        end_time: str,
        message_source: str | None = None,
    ) -> list[sqlite3.Row]:
        filters = ["created_time BETWEEN ? AND ?"]
        params: list[object] = [start_time, end_time]
        if message_source and message_source != "All":
            filters.append("message_source = ?")
            params.append(message_source)
        return self._fetch_all(
            """
            SELECT COALESCE(message_type, 'UNKNOWN') AS message_type, COUNT(*) AS total
            FROM messages
            WHERE """ + " AND ".join(filters) + """
            GROUP BY COALESCE(message_type, 'UNKNOWN')
            ORDER BY total DESC
            """,
            tuple(params),
        )
