from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.database.db import db_session
from app.database.repositories.base_repository import BaseRepository


class MemberReviewRepository(BaseRepository):
    def create_application(
        self,
        *,
        discord_username: str,
        discord_user_id: str,
        raw_application: str,
        player_name: str | None,
        server_id: str | None,
        raw_server_input: str | None,
        server_name: str | None,
        discord_nickname: str | None,
        review_status: str,
        reason_code: str,
        internal_reason: str,
        rejection_reason: str | None,
        confidence: float,
        auto_approvable: bool,
    ) -> int:
        return self._execute(
            """
            INSERT INTO member_applications (
                discord_username, discord_user_id, raw_application, player_name,
                server_id, raw_server_input, server_name, discord_nickname,
                review_status, reason_code, internal_reason, rejection_reason,
                confidence, auto_approvable
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                discord_username,
                discord_user_id,
                raw_application,
                player_name,
                server_id,
                raw_server_input,
                server_name,
                discord_nickname,
                review_status,
                reason_code,
                internal_reason,
                rejection_reason,
                confidence,
                1 if auto_approvable else 0,
            ),
        )

    def get_open_by_discord_user_id(self, discord_user_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT *
            FROM member_applications
            WHERE discord_user_id = ?
              AND processed = 0
            ORDER BY created_time DESC, id DESC
            LIMIT 1
            """,
            (discord_user_id,),
        )

    def update_open_application(
        self,
        *,
        application_id: int,
        discord_username: str,
        raw_application: str,
        player_name: str | None,
        server_id: str | None,
        raw_server_input: str | None,
        server_name: str | None,
        discord_nickname: str | None,
        review_status: str,
        reason_code: str,
        internal_reason: str,
        rejection_reason: str | None,
        confidence: float,
        auto_approvable: bool,
    ) -> None:
        with db_session(self.db_path) as connection:
            connection.execute(
                """
                UPDATE member_applications
                SET discord_username = ?,
                    raw_application = ?,
                    player_name = ?,
                    server_id = ?,
                    raw_server_input = ?,
                    server_name = ?,
                    discord_nickname = ?,
                    review_status = ?,
                    reason_code = ?,
                    internal_reason = ?,
                    rejection_reason = ?,
                    confidence = ?,
                    auto_approvable = ?,
                    updated_time = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND processed = 0
                """,
                (
                    discord_username,
                    raw_application,
                    player_name,
                    server_id,
                    raw_server_input,
                    server_name,
                    discord_nickname,
                    review_status,
                    reason_code,
                    internal_reason,
                    rejection_reason,
                    confidence,
                    1 if auto_approvable else 0,
                    application_id,
                ),
            )

    def list_filtered(
        self,
        *,
        review_status: str = "All",
        server_id: str = "All",
        processed_filter: str = "All",
        auto_filter: str = "All",
        limit: int = 300,
    ) -> list[sqlite3.Row]:
        filters: list[str] = ["1 = 1"]
        params: list[Any] = []
        if review_status != "All":
            filters.append("review_status = ?")
            params.append(review_status)
        if server_id != "All":
            filters.append("server_id = ?")
            params.append(server_id)
        if processed_filter == "未处理":
            filters.append("processed = 0")
        elif processed_filter == "已处理":
            filters.append("processed = 1")
        if auto_filter == "可自动通过":
            filters.append("auto_approvable = 1")
        elif auto_filter == "不可自动通过":
            filters.append("auto_approvable = 0")
        params.append(limit)
        return self._fetch_all(
            """
            SELECT *
            FROM member_applications
            WHERE """ + " AND ".join(filters) + """
            ORDER BY created_time DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        )

    def get(self, application_id: int) -> sqlite3.Row | None:
        return self._fetch_one("SELECT * FROM member_applications WHERE id = ?", (application_id,))

    def get_latest_by_discord_user_id(self, discord_user_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT * FROM member_applications
            WHERE discord_user_id = ?
            ORDER BY created_time DESC, id DESC
            LIMIT 1
            """,
            (discord_user_id,),
        )

    def counts(self) -> dict[str, int]:
        rows = self._fetch_all(
            """
            SELECT review_status, COUNT(*) AS total
            FROM member_applications
            WHERE processed = 0
            GROUP BY review_status
            """
        )
        counts = {str(row["review_status"]): int(row["total"] or 0) for row in rows}
        counts["待审核"] = sum(counts.values())
        return counts

    def update_review_result(
        self,
        *,
        application_id: int,
        review_status: str,
        final_result: str,
        rejection_reason: str | None,
        nickname_result: str | None,
        discord_api_result: str | None,
        reviewer: str | None,
    ) -> None:
        with db_session(self.db_path) as connection:
            connection.execute(
                """
                UPDATE member_applications
                SET review_status = ?,
                    final_result = ?,
                    rejection_reason = COALESCE(?, rejection_reason),
                    nickname_result = ?,
                    discord_api_result = ?,
                    reviewer = ?,
                    reviewed_time = CURRENT_TIMESTAMP,
                    processed = 1,
                    updated_time = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    review_status,
                    final_result,
                    rejection_reason,
                    nickname_result,
                    discord_api_result,
                    reviewer,
                    application_id,
                ),
            )

    def create_log(
        self,
        *,
        application_id: int,
        discord_username: str | None,
        discord_user_id: str | None,
        raw_application: str | None,
        player_name: str | None,
        server_id: str | None,
        server_name: str | None,
        discord_nickname: str | None,
        system_status: str | None,
        final_result: str,
        rejection_reason: str | None,
        reviewer: str | None,
        nickname_result: str | None,
        discord_api_result: str | None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO member_review_logs (
                application_id, discord_username, discord_user_id, raw_application,
                player_name, server_id, server_name, discord_nickname, system_status,
                final_result, rejection_reason, reviewer, nickname_result, discord_api_result
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                discord_username,
                discord_user_id,
                raw_application,
                player_name,
                server_id,
                server_name,
                discord_nickname,
                system_status,
                final_result,
                rejection_reason,
                reviewer,
                nickname_result,
                discord_api_result,
            ),
        )

    def list_logs(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT *
            FROM member_review_logs
            ORDER BY review_time DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
