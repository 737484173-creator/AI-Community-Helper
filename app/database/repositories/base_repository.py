from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.database.db import db_session


class BaseRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path

    def _fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with db_session(self.db_path) as connection:
            return connection.execute(query, params).fetchone()

    def _fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with db_session(self.db_path) as connection:
            return connection.execute(query, params).fetchall()

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> int:
        with db_session(self.db_path) as connection:
            cursor = connection.execute(query, params)
            return int(cursor.lastrowid)

