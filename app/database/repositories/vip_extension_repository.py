from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class PlayerProfileRepository(BaseRepository):
    def upsert(
        self,
        player_id: str,
        server_id: str,
        display_name: str | None = None,
        last_login_time: str | None = None,
        profile_json: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO player_profiles (
                player_id, server_id, display_name, last_login_time, profile_json
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(player_id, server_id) DO UPDATE SET
                display_name = excluded.display_name,
                last_login_time = excluded.last_login_time,
                profile_json = excluded.profile_json,
                updated_time = CURRENT_TIMESTAMP
            """,
            (player_id, server_id, display_name, last_login_time, profile_json),
        )

    def get(self, player_id: str, server_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT * FROM player_profiles
            WHERE player_id = ? AND server_id = ?
            """,
            (player_id, server_id),
        )


class VIPProfileRepository(BaseRepository):
    def upsert(
        self,
        player_id: str,
        server_id: str,
        vip_level: int | None = None,
        total_payment_amount: float | None = None,
        last_payment_time: str | None = None,
        payment_summary_json: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO vip_profiles (
                player_id, server_id, vip_level, total_payment_amount,
                last_payment_time, payment_summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, server_id) DO UPDATE SET
                vip_level = excluded.vip_level,
                total_payment_amount = excluded.total_payment_amount,
                last_payment_time = excluded.last_payment_time,
                payment_summary_json = excluded.payment_summary_json,
                updated_time = CURRENT_TIMESTAMP
            """,
            (
                player_id,
                server_id,
                vip_level,
                total_payment_amount,
                last_payment_time,
                payment_summary_json,
            ),
        )

    def get(self, player_id: str, server_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT * FROM vip_profiles
            WHERE player_id = ? AND server_id = ?
            """,
            (player_id, server_id),
        )


class RiskProfileRepository(BaseRepository):
    def upsert(
        self,
        player_id: str,
        server_id: str,
        risk_score: float | None = None,
        risk_level: str | None = None,
        risk_reason_json: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO risk_profiles (
                player_id, server_id, risk_score, risk_level, risk_reason_json
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(player_id, server_id) DO UPDATE SET
                risk_score = excluded.risk_score,
                risk_level = excluded.risk_level,
                risk_reason_json = excluded.risk_reason_json,
                updated_time = CURRENT_TIMESTAMP
            """,
            (player_id, server_id, risk_score, risk_level, risk_reason_json),
        )

    def get(self, player_id: str, server_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT * FROM risk_profiles
            WHERE player_id = ? AND server_id = ?
            """,
            (player_id, server_id),
        )

