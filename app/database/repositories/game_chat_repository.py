from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence

from app.database.db import db_session
from app.database.repositories.base_repository import BaseRepository
from app.vip.server_merges import current_server_merge_map, normalize_server_id


class GameChatRepository(BaseRepository):
    """Store AE game-chat detail separately from Discord community messages."""

    def replace_window(
        self,
        project_id: int,
        range_start: str,
        range_end: str,
        rows: Iterable[Mapping[str, object]],
        *,
        started_at: str,
        finished_at: str,
        source_row_count: int,
        active_role_count: int,
    ) -> int:
        message_rows = list(rows)
        with db_session(self.db_path) as connection:
            connection.execute(
                """
                DELETE FROM game_chat_messages
                WHERE project_id = ?
                  AND event_time >= ?
                  AND event_time <= ?
                """,
                (project_id, _day_start(range_start), _day_end(range_end)),
            )
            connection.executemany(
                """
                INSERT INTO game_chat_messages (
                    message_key, project_id, event_time, role_id,
                    server_id, server_name, chat_content, chat_channel,
                    chat_type, risk_level, risk_type, risk_reason,
                    source_event, synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["message_key"],
                        project_id,
                        row["event_time"],
                        row["role_id"],
                        row.get("server_id"),
                        row.get("server_name"),
                        row["chat_content"],
                        row.get("chat_channel"),
                        row.get("chat_type") or "发言",
                        row.get("risk_level"),
                        row.get("risk_type"),
                        row.get("risk_reason"),
                        row.get("source_event") or "role_chat",
                        finished_at,
                    )
                    for row in message_rows
                ],
            )
            cursor = connection.execute(
                """
                INSERT INTO game_chat_sync_runs (
                    project_id, status, started_at, finished_at,
                    range_start, range_end, source_row_count,
                    matched_row_count, active_role_count
                )
                VALUES (?, 'SUCCESS', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    started_at,
                    finished_at,
                    range_start,
                    range_end,
                    source_row_count,
                    len(message_rows),
                    active_role_count,
                ),
            )
            return int(cursor.lastrowid)

    def record_failure(
        self,
        project_id: int,
        range_start: str,
        range_end: str,
        *,
        started_at: str,
        finished_at: str,
        error_message: str,
        active_role_count: int = 0,
    ) -> int:
        with db_session(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO game_chat_sync_runs (
                    project_id, status, started_at, finished_at,
                    range_start, range_end, active_role_count, error_message
                )
                VALUES (?, 'FAILED', ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    started_at,
                    finished_at,
                    range_start,
                    range_end,
                    active_role_count,
                    error_message[:2000],
                ),
            )
            return int(cursor.lastrowid)

    def list_messages(
        self,
        project_id: int,
        range_start: str,
        range_end: str,
        *,
        server_ids: Sequence[str] = (),
        risk_only: bool = False,
    ) -> list[dict[str, object]]:
        conditions = [
            "project_id = ?",
            "event_time >= ?",
            "event_time <= ?",
        ]
        params: list[object] = [
            project_id,
            _day_start(range_start),
            _day_end(range_end),
        ]
        merge_map = current_server_merge_map()
        selected_servers = {
            merge_map.get(normalized, normalized)
            for value in server_ids
            if (normalized := normalize_server_id(value))
        }
        cleaned_servers = tuple(sorted(
            selected_servers
            | {source for source, primary in merge_map.items() if primary in selected_servers}
        ))
        if cleaned_servers:
            placeholders = ", ".join("?" for _ in cleaned_servers)
            conditions.append(f"server_id IN ({placeholders})")
            params.extend(cleaned_servers)
        if risk_only:
            conditions.append("risk_level IS NOT NULL")

        rows = self._fetch_all(
            f"""
            SELECT *
            FROM game_chat_messages
            WHERE {' AND '.join(conditions)}
            ORDER BY event_time DESC, message_key DESC
            """,
            tuple(params),
        )
        result = []
        for row in rows:
            item = dict(row)
            source = normalize_server_id(item["server_id"])
            primary = merge_map.get(source, source)
            if primary != source:
                item["server_id"] = primary
                item["server_name"] = f"S{primary}" if primary.isdigit() else primary
            result.append(item)
        return result

    def list_servers(
        self,
        project_id: int,
        range_start: str,
        range_end: str,
    ) -> list[dict[str, object]]:
        rows = self._fetch_all(
            """
            SELECT server_id, MAX(server_name) AS server_name, COUNT(*) AS message_count
            FROM game_chat_messages
            WHERE project_id = ?
              AND event_time >= ?
              AND event_time <= ?
              AND TRIM(COALESCE(server_id, '')) != ''
            GROUP BY server_id
            ORDER BY CAST(server_id AS INTEGER), server_id
            """,
            (project_id, _day_start(range_start), _day_end(range_end)),
        )
        merge_map = current_server_merge_map()
        totals: dict[str, dict[str, object]] = {}
        for row in rows:
            source = normalize_server_id(row["server_id"])
            primary = merge_map.get(source, source)
            if primary not in totals:
                totals[primary] = {
                    "server_id": primary,
                    "server_name": f"S{primary}" if primary.isdigit() else row["server_name"],
                    "message_count": 0,
                }
            totals[primary]["message_count"] += int(row["message_count"])
        return sorted(
            totals.values(),
            key=lambda row: (0, int(row["server_id"]))
            if str(row["server_id"]).isdigit()
            else (1, str(row["server_id"])),
        )

    def get_latest_run(self, project_id: int) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT *
            FROM game_chat_sync_runs
            WHERE project_id = ?
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """,
            (project_id,),
        )

    def get_covering_success(
        self,
        project_id: int,
        range_start: str,
        range_end: str,
    ) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT *
            FROM game_chat_sync_runs
            WHERE project_id = ?
              AND status = 'SUCCESS'
              AND range_start <= ?
              AND range_end >= ?
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """,
            (project_id, range_start, range_end),
        )


def _day_start(value: str) -> str:
    return f"{value[:10]} 00:00:00"


def _day_end(value: str) -> str:
    return f"{value[:10]} 23:59:59.999"
