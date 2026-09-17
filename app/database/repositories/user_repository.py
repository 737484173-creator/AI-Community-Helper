from __future__ import annotations

import sqlite3

from app.database.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository):
    def get_by_discord_id(self, discord_user_id: str) -> sqlite3.Row | None:
        return self._fetch_one(
            "SELECT * FROM users WHERE discord_user_id = ?",
            (discord_user_id,),
        )

    def get_or_create(
        self,
        discord_user_id: str,
        player_id: str | None = None,
        server_id: str | None = None,
        discord_user_name: str | None = None,
    ) -> sqlite3.Row:
        existing = self.get_by_discord_id(discord_user_id)
        if existing:
            if discord_user_name and discord_user_name != existing["discord_user_name"]:
                self.update_discord_user_name(discord_user_id, discord_user_name)
                updated = self.get_by_discord_id(discord_user_id)
                return updated or existing
            return existing

        self._execute(
            """
            INSERT INTO users (discord_user_id, discord_user_name, player_id, server_id)
            VALUES (?, ?, ?, ?)
            """,
            (discord_user_id, discord_user_name, player_id, server_id),
        )
        created = self.get_by_discord_id(discord_user_id)
        if created is None:
            raise RuntimeError("Failed to create user.")
        return created

    def update_discord_user_name(self, discord_user_id: str, discord_user_name: str) -> None:
        clean_name = discord_user_name.strip()
        if not clean_name:
            return
        self._execute(
            """
            UPDATE users
            SET discord_user_name = ?, updated_time = CURRENT_TIMESTAMP
            WHERE discord_user_id = ?
            """,
            (clean_name, discord_user_id),
        )
