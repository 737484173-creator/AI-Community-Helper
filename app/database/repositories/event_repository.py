from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class EventRepository(BaseRepository):
    def create(
        self,
        title: str,
        content: str,
        event_type: str,
        channel_id: str,
        publish_time: str,
        repeat_rule: str = "none",
        status: str = "Draft",
        event_options_json: str | None = None,
        event_image_path: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO events (
                title, content, event_type, event_options_json, event_image_path,
                channel_id, publish_time, repeat_rule, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                content,
                event_type,
                event_options_json,
                event_image_path,
                channel_id,
                publish_time,
                repeat_rule,
                status,
            ),
        )

    def list_scheduled(self) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM events
            WHERE status = 'Scheduled'
            ORDER BY publish_time ASC
            """
        )

    def list_due(self, now: str) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM events
            WHERE status = 'Scheduled'
              AND publish_time <= ?
            ORDER BY publish_time ASC, id ASC
            """,
            (now,),
        )

    def list_recent(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM events
            ORDER BY created_time DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def get_by_id(self, event_id: int) -> sqlite3.Row | None:
        return self._fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))

    def list_filtered(
        self,
        status: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM events WHERE 1 = 1"
        params: list[object] = []
        if status and status != "All":
            query += " AND status = ?"
            params.append(status)
        if event_type and event_type != "All":
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY publish_time DESC, id DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(query, tuple(params))

    def list_published_with_discord_message(self) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM events
            WHERE discord_message_id IS NOT NULL
              AND status IN ('Published', 'Scheduled', 'Completed')
            ORDER BY updated_time DESC, id DESC
            """
        )

    def update_status(
        self,
        event_id: int,
        status: str,
        discord_message_id: str | None = None,
    ) -> None:
        self._execute(
            """
            UPDATE events
            SET status = ?,
                discord_message_id = COALESCE(?, discord_message_id),
                updated_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, discord_message_id, event_id),
        )

    def reschedule(
        self,
        event_id: int,
        next_publish_time: str,
        status: str = "Scheduled",
        discord_message_id: str | None = None,
    ) -> None:
        self._execute(
            """
            UPDATE events
            SET publish_time = ?,
                status = ?,
                discord_message_id = COALESCE(?, discord_message_id),
                updated_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (next_publish_time, status, discord_message_id, event_id),
        )
