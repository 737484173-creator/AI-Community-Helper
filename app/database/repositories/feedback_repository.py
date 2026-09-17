from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class FeedbackRepository(BaseRepository):
    def create(
        self,
        discord_user_id: str,
        content: str,
        category: str,
        discord_user_name: str | None = None,
        channel_id: str | None = None,
        channel_name: str | None = None,
        thread_title: str | None = None,
        feature: str | None = None,
        keywords: str | None = None,
        sentiment: str = "Neutral",
        priority: str = "Low",
        status: str = "Open",
    ) -> int:
        return self._execute(
            """
            INSERT INTO feedback (
                discord_user_id, discord_user_name, channel_id, channel_name, thread_title, content, category, feature, keywords,
                sentiment, priority, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                discord_user_id,
                discord_user_name,
                channel_id,
                channel_name,
                thread_title,
                content,
                category,
                feature,
                keywords,
                sentiment,
                priority,
                status,
            ),
        )

    def list_open(self) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                feedback.*,
                COALESCE(feedback.channel_name, discord_channels.channel_name) AS display_channel_name
            FROM feedback
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = feedback.channel_id
            WHERE status IN ('Open', 'In Progress')
            ORDER BY
                CASE priority
                    WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2
                    ELSE 3
                END,
                created_time DESC
            """
        )

    def count_between(self, start_time: str, end_time: str) -> int:
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM feedback
            WHERE created_time BETWEEN ? AND ?
            """,
            (start_time, end_time),
        )
        return int(row["total"] if row else 0)

    def count_high_priority_between(self, start_time: str, end_time: str) -> int:
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM feedback
            WHERE created_time BETWEEN ? AND ?
              AND priority = 'High'
            """,
            (start_time, end_time),
        )
        return int(row["total"] if row else 0)

    def count_by_status(
        self,
        status: str,
        channel_names: tuple[str, ...] | None = None,
        excluded_user_ids: tuple[str, ...] | None = None,
    ) -> int:
        filters = ["status = ?"]
        params: list[object] = [status]
        if channel_names:
            placeholders = ", ".join("?" for _ in channel_names)
            filters.append(f"channel_name IN ({placeholders})")
            params.extend(channel_names)
        if excluded_user_ids:
            placeholders = ", ".join("?" for _ in excluded_user_ids)
            filters.append(f"discord_user_id NOT IN ({placeholders})")
            params.extend(excluded_user_ids)

        row = self._fetch_one(
            f"""
            SELECT COUNT(*) AS total
            FROM feedback
            WHERE {' AND '.join(filters)}
            """,
            tuple(params),
        )
        return int(row["total"] if row else 0)

    def count_by_category_between(self, start_time: str, end_time: str) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT category, COUNT(*) AS total
            FROM feedback
            WHERE created_time BETWEEN ? AND ?
            GROUP BY category
            ORDER BY total DESC
            """,
            (start_time, end_time),
        )

    def count_by_sentiment_between(self, start_time: str, end_time: str) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT sentiment, COUNT(*) AS total
            FROM feedback
            WHERE created_time BETWEEN ? AND ?
            GROUP BY sentiment
            ORDER BY total DESC
            """,
            (start_time, end_time),
        )

    def count_open_by_date_between(
        self,
        start_date: str,
        end_date: str,
        channel_names: tuple[str, ...] | None = None,
        excluded_user_ids: tuple[str, ...] | None = None,
    ) -> dict[str, int]:
        filters = ["date(created_time) BETWEEN ? AND ?"]
        params: list[object] = [start_date, end_date]
        if channel_names:
            placeholders = ", ".join("?" for _ in channel_names)
            filters.append(f"channel_name IN ({placeholders})")
            params.extend(channel_names)
        if excluded_user_ids:
            placeholders = ", ".join("?" for _ in excluded_user_ids)
            filters.append(f"discord_user_id NOT IN ({placeholders})")
            params.extend(excluded_user_ids)

        rows = self._fetch_all(
            """
            SELECT
                date(created_time) AS feedback_date,
                SUM(CASE WHEN status IN ('Open', 'In Progress') THEN 1 ELSE 0 END) AS open_total
            FROM feedback
            WHERE """ + " AND ".join(filters) + """
            GROUP BY date(created_time)
            """,
            tuple(params),
        )
        return {str(row["feedback_date"]): int(row["open_total"] or 0) for row in rows}

    def list_top_open(self, limit: int = 10) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                feedback.*,
                COALESCE(feedback.channel_name, discord_channels.channel_name) AS display_channel_name
            FROM feedback
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = feedback.channel_id
            WHERE status IN ('Open', 'In Progress')
            ORDER BY
                CASE priority
                    WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2
                    ELSE 3
                END,
                created_time DESC
            LIMIT ?
            """,
            (limit,),
        )

    def list_recent(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                feedback.*,
                COALESCE(feedback.channel_name, discord_channels.channel_name) AS display_channel_name
            FROM feedback
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = feedback.channel_id
            ORDER BY feedback.created_time DESC, feedback.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def list_status_update_candidates(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                feedback.*,
                COALESCE(feedback.channel_name, discord_channels.channel_name) AS display_channel_name
            FROM feedback
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = feedback.channel_id
            WHERE status IN ('Open', 'In Progress')
            ORDER BY feedback.updated_time DESC, feedback.created_time DESC, feedback.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def list_recent_for_dedupe(
        self,
        discord_user_id: str,
        channel_name: str,
        thread_title: str | None = None,
        limit: int = 30,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT *
            FROM feedback
            WHERE discord_user_id = ?
              AND channel_name = ?
              AND status IN ('Open', 'In Progress')
        """
        params: list[object] = [discord_user_id, channel_name]
        if thread_title:
            query += " AND COALESCE(thread_title, '') = ?"
            params.append(thread_title)
        query += """
            ORDER BY created_time DESC, id DESC
            LIMIT ?
        """
        params.append(limit)
        return self._fetch_all(query, tuple(params))

    def get_first_by_thread(
        self,
        channel_name: str,
        thread_title: str,
    ) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT *
            FROM feedback
            WHERE channel_name = ? COLLATE NOCASE
              AND TRIM(thread_title) = TRIM(?) COLLATE NOCASE
            ORDER BY created_time ASC, id ASC
            LIMIT 1
            """,
            (channel_name, thread_title),
        )

    def list_filtered(
        self,
        start_time: str,
        end_time: str,
        category: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        channel_names: tuple[str, ...] | None = None,
        excluded_user_ids: tuple[str, ...] | None = None,
        limit: int = 300,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT
                feedback.*,
                COALESCE(feedback.channel_name, discord_channels.channel_name) AS display_channel_name
            FROM feedback
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = feedback.channel_id
            WHERE feedback.created_time BETWEEN ? AND ?
        """
        params: list[object] = [start_time, end_time]
        if category and category != "All":
            query += " AND feedback.category = ?"
            params.append(category)
        if priority and priority != "All":
            query += " AND feedback.priority = ?"
            params.append(priority)
        if status and status != "All":
            query += " AND feedback.status = ?"
            params.append(status)
        if channel_names:
            placeholders = ", ".join("?" for _ in channel_names)
            query += f" AND feedback.channel_name IN ({placeholders})"
            params.extend(channel_names)
        if excluded_user_ids:
            placeholders = ", ".join("?" for _ in excluded_user_ids)
            query += f" AND feedback.discord_user_id NOT IN ({placeholders})"
            params.extend(excluded_user_ids)
        query += """
            ORDER BY
                CASE feedback.priority
                    WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2
                    ELSE 3
                END,
                feedback.created_time DESC,
                feedback.id DESC
            LIMIT ?
        """
        params.append(limit)
        return self._fetch_all(query, tuple(params))

    def update_status(self, feedback_id: int, status: str) -> None:
        self._execute(
            """
            UPDATE feedback
            SET status = ?,
                updated_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, feedback_id),
        )

    def update_thread_status(self, feedback_id: int, status: str) -> None:
        row = self._fetch_one(
            "SELECT channel_name, thread_title FROM feedback WHERE id = ?",
            (feedback_id,),
        )
        if row is None or not str(row["thread_title"] or "").strip():
            self.update_status(feedback_id, status)
            return

        self._execute(
            """
            UPDATE feedback
            SET status = ?,
                updated_time = CURRENT_TIMESTAMP
            WHERE channel_name = ? COLLATE NOCASE
              AND TRIM(thread_title) = TRIM(?) COLLATE NOCASE
            """,
            (status, row["channel_name"], row["thread_title"]),
        )

    def list_between(self, start_time: str, end_time: str, limit: int = 20) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                feedback.*,
                COALESCE(feedback.channel_name, discord_channels.channel_name) AS display_channel_name
            FROM feedback
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = feedback.channel_id
            WHERE feedback.created_time BETWEEN ? AND ?
            ORDER BY
                CASE feedback.priority
                    WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2
                    ELSE 3
                END,
                feedback.created_time DESC,
                feedback.id DESC
            LIMIT ?
            """,
            (start_time, end_time, limit),
        )
