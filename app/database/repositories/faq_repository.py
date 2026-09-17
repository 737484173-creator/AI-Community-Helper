from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class FAQRepository(BaseRepository):
    def upsert(
        self,
        category: str,
        question: str,
        answer: str,
        subcategory: str | None = None,
        keywords: str | None = None,
        enabled: bool = True,
    ) -> int:
        return self._execute(
            """
            INSERT INTO faq (category, subcategory, question, answer, keywords, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(category, question) DO UPDATE SET
                subcategory = excluded.subcategory,
                answer = excluded.answer,
                keywords = excluded.keywords,
                enabled = excluded.enabled,
                updated_time = CURRENT_TIMESTAMP
            """,
            (category, subcategory, question, answer, keywords, int(enabled)),
        )

    def list_categories(self) -> list[str]:
        rows = self._fetch_all(
            "SELECT DISTINCT category FROM faq WHERE enabled = 1 ORDER BY category"
        )
        return [str(row["category"]) for row in rows]

    def list_by_category(self, category: str) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM faq
            WHERE category = ? AND enabled = 1
            ORDER BY subcategory, question
            """,
            (category,),
        )

    def get_by_id(self, faq_id: int) -> sqlite3.Row | None:
        return self._fetch_one("SELECT * FROM faq WHERE id = ?", (faq_id,))

    def list_enabled(self) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM faq
            WHERE enabled = 1
            ORDER BY category, subcategory, question
            """
        )

    def list_all(self, limit: int = 200) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM faq
            ORDER BY category, subcategory, question
            LIMIT ?
            """,
            (limit,),
        )

    def count_all(self) -> int:
        row = self._fetch_one("SELECT COUNT(*) AS total FROM faq")
        return int(row["total"]) if row is not None else 0

    def set_enabled(self, faq_id: int, enabled: bool) -> None:
        self._execute(
            """
            UPDATE faq
            SET enabled = ?,
                updated_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(enabled), faq_id),
        )
