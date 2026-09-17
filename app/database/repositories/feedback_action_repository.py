from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class FeedbackActionRepository(BaseRepository):
    def create_bot_reply(
        self,
        feedback_id: int,
        content: str,
        discord_channel_id: str,
        discord_message_id: str,
        destination_label: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO feedback_action_logs (
                feedback_id,
                action_type,
                content,
                destination_label,
                discord_channel_id,
                discord_message_id
            )
            VALUES (?, 'BOT_REPLY', ?, ?, ?, ?)
            """,
            (
                feedback_id,
                content,
                destination_label,
                discord_channel_id,
                discord_message_id,
            ),
        )

    def list_by_feedback(self, feedback_id: int) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT *
            FROM feedback_action_logs
            WHERE feedback_id = ?
            ORDER BY created_time DESC, id DESC
            """,
            (feedback_id,),
        )
