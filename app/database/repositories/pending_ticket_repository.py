from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class PendingTicketRepository(BaseRepository):
    def create(
        self,
        discord_user_id: str,
        channel_id: str,
        original_message: str,
        selected_category: str | None = None,
        selected_question: str | None = None,
        issue_description: str | None = None,
        status: str = "Open",
        ticket_source: str = "AI_DM_UNRESOLVED",
    ) -> int:
        return self._execute(
            """
            INSERT INTO pending_tickets (
                discord_user_id, channel_id, ticket_source, original_message, selected_category,
                selected_question, issue_description, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                discord_user_id,
                channel_id,
                ticket_source,
                original_message,
                selected_category,
                selected_question,
                issue_description,
                status,
            ),
        )

    def list_open(self) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM pending_tickets
            WHERE status IN ('Open', 'In Progress')
            ORDER BY created_time DESC, id DESC
            """
        )

    def count_between(self, start_time: str, end_time: str) -> int:
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM pending_tickets
            WHERE created_time BETWEEN ? AND ?
            """,
            (start_time, end_time),
        )
        return int(row["total"] if row else 0)

    def count_open(self, ticket_source: str | None = None) -> int:
        filters = ["status IN ('Open', 'In Progress')"]
        params: list[object] = []
        if ticket_source:
            filters.append("ticket_source = ?")
            params.append(ticket_source)

        row = self._fetch_one(
            f"""
            SELECT COUNT(*) AS total
            FROM pending_tickets
            WHERE {' AND '.join(filters)}
            """,
            tuple(params),
        )
        return int(row["total"] if row else 0)

    def count_open_by_date_between(
        self,
        start_date: str,
        end_date: str,
        ticket_source: str | None = None,
    ) -> dict[str, int]:
        filters = ["date(created_time) BETWEEN ? AND ?"]
        params: list[object] = [start_date, end_date]
        if ticket_source:
            filters.append("ticket_source = ?")
            params.append(ticket_source)

        rows = self._fetch_all(
            """
            SELECT
                date(created_time) AS ticket_date,
                SUM(CASE WHEN status IN ('Open', 'In Progress') THEN 1 ELSE 0 END) AS open_total
            FROM pending_tickets
            WHERE """ + " AND ".join(filters) + """
            GROUP BY date(created_time)
            """,
            tuple(params),
        )
        return {str(row["ticket_date"]): int(row["open_total"] or 0) for row in rows}

    def list_recent(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                pending_tickets.*,
                COALESCE(discord_channels.channel_name, '未知频道 / 私信') AS channel_display_name
            FROM pending_tickets
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = pending_tickets.channel_id
            ORDER BY pending_tickets.created_time DESC, pending_tickets.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def get_by_id(self, ticket_id: int) -> sqlite3.Row | None:
        return self._fetch_one(
            """
            SELECT * FROM pending_tickets
            WHERE id = ?
            """,
            (ticket_id,),
        )

    def list_filtered(
        self,
        start_time: str,
        end_time: str,
        status: str | None = None,
        limit: int = 300,
    ) -> list[sqlite3.Row]:
        if status and status != "All":
            return self._fetch_all(
                """
                SELECT
                    pending_tickets.*,
                    COALESCE(discord_channels.channel_name, '未知频道 / 私信') AS channel_display_name
                FROM pending_tickets
                LEFT JOIN discord_channels
                    ON discord_channels.channel_id = pending_tickets.channel_id
                WHERE pending_tickets.created_time BETWEEN ? AND ?
                  AND pending_tickets.status = ?
                ORDER BY pending_tickets.created_time DESC, pending_tickets.id DESC
                LIMIT ?
                """,
                (start_time, end_time, status, limit),
            )

        return self._fetch_all(
            """
            SELECT
                pending_tickets.*,
                COALESCE(discord_channels.channel_name, '未知频道 / 私信') AS channel_display_name
            FROM pending_tickets
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = pending_tickets.channel_id
            WHERE pending_tickets.created_time BETWEEN ? AND ?
            ORDER BY pending_tickets.created_time DESC, pending_tickets.id DESC
            LIMIT ?
            """,
            (start_time, end_time, limit),
        )

    def update_status(self, ticket_id: int, status: str, assigned_to: str | None = None) -> None:
        self._execute(
            """
            UPDATE pending_tickets
            SET status = ?,
                assigned_to = COALESCE(?, assigned_to),
                updated_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, assigned_to, ticket_id),
        )

    def list_ai_dm_unresolved_filtered(
        self,
        start_time: str,
        end_time: str,
        status: str | None = None,
        limit: int = 300,
    ) -> list[sqlite3.Row]:
        filters = [
            "pending_tickets.created_time BETWEEN ? AND ?",
            "pending_tickets.ticket_source = 'AI_DM_UNRESOLVED'",
        ]
        params: list[object] = [start_time, end_time]
        if status and status != "All":
            filters.append("pending_tickets.status = ?")
            params.append(status)

        params.append(limit)
        return self._fetch_all(
            """
            SELECT
                pending_tickets.*,
                COALESCE(discord_channels.channel_name, '未知频道 / 私信') AS channel_display_name
            FROM pending_tickets
            LEFT JOIN discord_channels
                ON discord_channels.channel_id = pending_tickets.channel_id
            WHERE """ + " AND ".join(filters) + """
            ORDER BY pending_tickets.created_time DESC, pending_tickets.id DESC
            LIMIT ?
            """,
            tuple(params),
        )

    def mark_resolved(self, ticket_id: int, assigned_to: str | None = None) -> None:
        self.update_status(ticket_id, "Closed", assigned_to)

    def delete(self, ticket_id: int) -> None:
        self._execute(
            """
            DELETE FROM pending_tickets
            WHERE id = ?
            """,
            (ticket_id,),
        )


class PendingTicketNoteRepository(BaseRepository):
    def create(
        self,
        ticket_id: int,
        note: str,
        operator_name: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO pending_ticket_notes (ticket_id, operator_name, note)
            VALUES (?, ?, ?)
            """,
            (ticket_id, operator_name, note),
        )

    def list_by_ticket(self, ticket_id: int) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT * FROM pending_ticket_notes
            WHERE ticket_id = ?
            ORDER BY created_time DESC, id DESC
            """,
            (ticket_id,),
        )

    def list_recent(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._fetch_all(
            """
            SELECT
                pending_ticket_notes.*,
                pending_tickets.discord_user_id,
                pending_tickets.status
            FROM pending_ticket_notes
            JOIN pending_tickets ON pending_tickets.id = pending_ticket_notes.ticket_id
            ORDER BY pending_ticket_notes.created_time DESC,
                     pending_ticket_notes.id DESC
            LIMIT ?
            """,
            (limit,),
        )
