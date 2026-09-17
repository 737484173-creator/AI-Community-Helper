from __future__ import annotations

import sqlite3

from app.database.db import db_session
from app.database.repositories.base_repository import BaseRepository


class DiscordChannelRepository(BaseRepository):
    def upsert(
        self,
        channel_id: str,
        channel_name: str,
        channel_type: str | None = None,
        guild_id: str | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO discord_channels (channel_id, channel_name, channel_type, guild_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                channel_name = excluded.channel_name,
                channel_type = excluded.channel_type,
                guild_id = excluded.guild_id,
                updated_time = CURRENT_TIMESTAMP
            """,
            (channel_id, channel_name, channel_type, guild_id),
        )

    def get_by_channel_id(self, channel_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT * FROM discord_channels
            WHERE channel_id = ?
            """,
            (channel_id,),
        )

    def find_thread_by_name(
        self,
        thread_title: str,
        guild_id: str | None = None,
    ) -> sqlite3.Row | None:
        query = """
            SELECT *
            FROM discord_channels
            WHERE channel_type = 'Thread'
              AND TRIM(channel_name) = TRIM(?) COLLATE NOCASE
        """
        params: list[object] = [thread_title]
        if guild_id:
            query += " AND guild_id = ?"
            params.append(guild_id)
        query += " ORDER BY updated_time DESC LIMIT 1"
        return self._fetch_one(query, tuple(params))

    def list_publishable(self) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM discord_channels
            WHERE channel_type IN (
                'TextChannel',
                'ForumChannel',
                'StageChannel',
                'VoiceChannel'
            )
            ORDER BY channel_name COLLATE NOCASE ASC
            """
        )

    def list_uncached_reference_ids(self, limit: int = 500) -> list[str]:
        with db_session(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT channel_id
                FROM (
                    SELECT channel_id FROM messages
                    UNION
                    SELECT channel_id FROM pending_tickets
                    UNION
                    SELECT channel_id FROM events
                ) AS referenced_channels
                WHERE channel_id NOT IN (
                    SELECT channel_id FROM discord_channels
                )
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [str(row["channel_id"]) for row in rows]
