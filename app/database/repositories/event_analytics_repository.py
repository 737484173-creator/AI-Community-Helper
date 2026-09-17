from __future__ import annotations

from app.database.repositories.base_repository import BaseRepository


class EventAnalyticsRepository(BaseRepository):
    def create_initial(self, event_id: int, published_time: str | None = None) -> int:
        return self._execute(
            """
            INSERT INTO event_analytics (event_id, published_time)
            VALUES (?, ?)
            """,
            (event_id, published_time),
        )

    def update_metrics(
        self,
        analytics_id: int,
        participant_count: int,
        reaction_count: int,
        poll_result_json: str | None = None,
    ) -> None:
        self._execute(
            """
            UPDATE event_analytics
            SET participant_count = ?,
                reaction_count = ?,
                poll_result_json = ?,
                updated_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (participant_count, reaction_count, poll_result_json, analytics_id),
        )

    def list_by_event(self, event_id: int):
        return self._fetch_all(
            """
            SELECT * FROM event_analytics
            WHERE event_id = ?
            ORDER BY published_time DESC, id DESC
            """,
            (event_id,),
        )

    def get_latest_by_event(self, event_id: int):
        return self._fetch_one(
            """
            SELECT * FROM event_analytics
            WHERE event_id = ?
            ORDER BY published_time DESC, id DESC
            LIMIT 1
            """,
            (event_id,),
        )

    def list_recent_with_events(self, limit: int = 50):
        return self._fetch_all(
            """
            SELECT
                event_analytics.*,
                events.title,
                events.event_type,
                events.channel_id,
                events.discord_message_id
            FROM event_analytics
            JOIN events ON events.id = event_analytics.event_id
            ORDER BY event_analytics.updated_time DESC, event_analytics.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def list_between_with_events(self, start_time: str, end_time: str, limit: int = 20):
        return self._fetch_all(
            """
            SELECT
                event_analytics.*,
                events.title,
                events.event_type,
                events.channel_id,
                events.discord_message_id
            FROM event_analytics
            JOIN events ON events.id = event_analytics.event_id
            WHERE event_analytics.published_time BETWEEN ? AND ?
            ORDER BY event_analytics.reaction_count DESC,
                     event_analytics.participant_count DESC,
                     event_analytics.id DESC
            LIMIT ?
            """,
            (start_time, end_time, limit),
        )
