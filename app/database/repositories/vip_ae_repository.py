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
        purchase_rows: Iterable[Mapping[str, object]] = (),
        started_at: str,
        finished_at: str,
        source_row_count: int,
        cumulative_window: str,
        weekly_window: str,
        previous_week_window: str = "",
        rolling_28d_window: str = "",
        purchase_source_row_count: int = 0,
        purchase_lifetime_window: str = "",
        purchase_7d_window: str = "",
        purchase_14d_window: str = "",
        purchase_recent_window: str = "",
    ) -> int:
        snapshot_rows = list(rows)
        package_rows = list(purchase_rows)
        with db_session(self.db_path) as connection:
            connection.execute(
                "DELETE FROM vip_ae_snapshots WHERE project_id = ?",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM vip_purchase_packages WHERE project_id = ?",
                (project_id,),
            )
            connection.executemany(
                """
                INSERT INTO vip_ae_snapshots (
                    project_id, role_id, role_name, server_id, server_name,
                    last_login_time, total_payment_amount, payment_7d_amount,
                    payment_previous_7d_amount, payment_28d_weekly_avg,
                    cps_group, server_type, user_source,
                    build_fp, tech_fp, soldier_fp, beast_fp, hero_fp,
                    hiryu_fp, com_fp, leg_tech_fp, cur_fp, synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        row.get("build_fp"),
                        row.get("tech_fp"),
                        row.get("soldier_fp"),
                        row.get("beast_fp"),
                        row.get("hero_fp"),
                        row.get("hiryu_fp"),
                        row.get("com_fp"),
                        row.get("leg_tech_fp"),
                        row.get("cur_fp"),
                        finished_at,
                    )
                    for row in snapshot_rows
                ],
            )
            connection.executemany(
                """
                INSERT INTO vip_purchase_packages (
                    project_id, role_id, window_key, window_label,
                    giftbox_id, giftbox_name, category, purchase_count,
                    payment_amount, payment_channel, currency_name,
                    source_event, is_demand_evidence, items_json, synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        project_id,
                        row["role_id"],
                        row["window_key"],
                        row.get("window_label"),
                        row["giftbox_id"],
                        row.get("giftbox_name"),
                        row["category"],
                        row.get("purchase_count", 0),
                        row.get("payment_amount", 0),
                        row.get("payment_channel", "cash"),
                        row.get("currency_name", "美元"),
                        row.get("source_event", "role_pay"),
                        int(bool(row.get("is_demand_evidence", True))),
                        row.get("items_json", "[]"),
                        finished_at,
                    )
                    for row in package_rows
                ],
            )
            cursor = connection.execute(
                """
                INSERT INTO vip_ae_sync_runs (
                    project_id, status, started_at, finished_at,
                    source_row_count, vip_row_count,
                    cumulative_window, weekly_window,
                    previous_week_window, rolling_28d_window,
                    purchase_source_row_count, purchase_vip_package_count,
                    purchase_lifetime_window, purchase_7d_window,
                    purchase_14d_window, purchase_recent_window
                )
                VALUES (?, 'SUCCESS', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    purchase_source_row_count,
                    len(package_rows),
                    purchase_lifetime_window,
                    purchase_7d_window,
                    purchase_14d_window,
                    purchase_recent_window,
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

    def get_latest_successful_run(self, project_id: int) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT *
            FROM vip_ae_sync_runs
            WHERE project_id = ? AND status = 'SUCCESS'
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """,
            (project_id,),
        )

    def list_purchase_packages(
        self,
        project_id: int,
        role_id: str,
    ) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT *
            FROM vip_purchase_packages
            WHERE project_id = ? AND role_id = ?
            ORDER BY window_key, payment_amount DESC, purchase_count DESC, giftbox_id
            """,
            (project_id, role_id),
        )

    def list_purchase_packages_by_channel(
        self,
        project_id: int,
        payment_channel: str,
    ) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT *
            FROM vip_purchase_packages
            WHERE project_id = ? AND payment_channel = ?
            ORDER BY role_id, window_key, payment_amount DESC, giftbox_id
            """,
            (project_id, payment_channel),
        )

    def count_purchase_packages(self, project_id: int) -> int:
        row = self._fetch_one(
            "SELECT COUNT(*) AS row_count FROM vip_purchase_packages WHERE project_id = ?",
            (project_id,),
        )
        return int(row["row_count"]) if row else 0
