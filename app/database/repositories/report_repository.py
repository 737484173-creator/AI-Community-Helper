from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class ReportRepository(BaseRepository):
    def create(
        self,
        report_type: str,
        title: str,
        content: str,
        start_time: str,
        end_time: str,
    ) -> int:
        return self._execute(
            """
            INSERT INTO reports (report_type, title, content, start_time, end_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report_type, title, content, start_time, end_time),
        )

    def list_recent(self, report_type: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
        if report_type:
            return self._fetch_all(
                """
                SELECT * FROM reports
                WHERE report_type = ?
                ORDER BY created_time DESC, id DESC
                LIMIT ?
                """,
                (report_type, limit),
            )

        return self._fetch_all(
            """
            SELECT * FROM reports
            ORDER BY created_time DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def get_by_id(self, report_id: int) -> sqlite3.Row | None:
        return self._fetch_one("SELECT * FROM reports WHERE id = ?", (report_id,))

    def list_by_types(self, report_types: tuple[str, ...]) -> list[sqlite3.Row]:
        if not report_types:
            return []
        placeholders = ", ".join("?" for _ in report_types)
        return self._fetch_all(
            f"""
            SELECT * FROM reports
            WHERE report_type IN ({placeholders})
            ORDER BY start_time ASC, id ASC
            """,
            tuple(report_types),
        )

    def update_content(self, report_id: int, content: str) -> None:
        self._execute(
            "UPDATE reports SET content = ? WHERE id = ?",
            (content, report_id),
        )

    def delete(self, report_id: int) -> None:
        self._execute("DELETE FROM reports WHERE id = ?", (report_id,))
