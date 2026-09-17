from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping

from app.database.db import db_session
from app.database.repositories.base_repository import BaseRepository


class AEVIPSnapshotRepository(BaseRepository):
    """Persist the latest complete AE-backed VIP snapshot and its sync history."""

    def replace_snapshot(
        self,
        project_id: int,
        rows: Iterable[Mapping[str, object]],
        *,
        started_at: str,
        finished_at: str,
        source_row_count: int,
        cumulative_window: str,
        weekly_window: str,
        previous_week_window: str = "",
        rolling_28d_window: str = "",
    ) -> int:
        snapshot_rows = list(rows)
        with db_session(self.db_path) as connection:
            connection.execute(
                "DELETE FROM vip_ae_snapshots WHERE project_id = ?",
                (project_id,),
            )
            connection.executemany(
                """
                INSERT INTO vip_ae_snapshots (
                    project_id, role_id, role_name, server_id, server_name,
                    last_login_time, total_payment_amount, payment_7d_amount,
                    payment_previous_7d_amount, payment_28d_weekly_avg,
                    cps_group, server_type, user_source, synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        project_id,
                        row["role_id"],
                        row.get("role_name"),
                        row.get("server_id"),
                        row.get("server_name"),
                        row.get("last_login_time"),
                        row["total_payment_amount"],
                        row["payment_7d_amount"],
                        row.get("payment_previous_7d_amount"),
                        row.get("payment_28d_weekly_avg"),
                        row.get("cps_group"),
                        row["server_type"],
                        row["user_source"],
                        finished_at,
                    )
                    for row in snapshot_rows
                ],
            )
            cursor = connection.execute(
                """
                INSERT INTO vip_ae_sync_runs (
                    project_id, status, started_at, finished_at,
                    source_row_count, vip_row_count,
                    cumulative_window, weekly_window,
                    previous_week_window, rolling_28d_window
                )
                VALUES (?, 'SUCCESS', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    started_at,
                    finished_at,
                    source_row_count,
                    len(snapshot_rows),
                    cumulative_window,
                    weekly_window,
                    previous_week_window,
                    rolling_28d_window,
                ),
            )
            return int(cursor.lastrowid)

    def record_failure(
        self,
        project_id: int,
        *,
        started_at: str,
        finished_at: str,
        error_message: str,
    ) -> int:
        with db_session(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO vip_ae_sync_runs (
                    project_id, status, started_at, finished_at, error_message
                )
                VALUES (?, 'FAILED', ?, ?, ?)
                """,
                (project_id, started_at, finished_at, error_message[:2000]),
            )
            return int(cursor.lastrowid)

    def list_snapshot(self, project_id: int) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT *
            FROM vip_ae_snapshots
            WHERE project_id = ?
            ORDER BY total_payment_amount DESC, role_id
            """,
            (project_id,),
        )

    def count_snapshot(self, project_id: int) -> int:
        row = self._fetch_one(
            "SELECT COUNT(*) AS row_count FROM vip_ae_snapshots WHERE project_id = ?",
            (project_id,),
        )
        return int(row["row_count"]) if row else 0

    def get_snapshot_summary(self, project_id: int) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT COUNT(*) AS row_count, MAX(synced_at) AS synced_at
            FROM vip_ae_snapshots
            WHERE project_id = ?
            """,
            (project_id,),
        )

    def get_latest_run(self, project_id: int) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT *
            FROM vip_ae_sync_runs
            WHERE project_id = ?
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """,
            (project_id,),
        )
