from __future__ import annotations

import sqlite3

from app.database.migrations.init_db import init_database
from app.database.repositories.game_chat_repository import GameChatRepository


def _message(key: str, event_time: str, *, server_id: str = "1") -> dict[str, object]:
    return {
        "message_key": key,
        "event_time": event_time,
        "role_id": "role-1",
        "server_id": server_id,
        "server_name": f"S{server_id}",
        "chat_content": "hello",
        "chat_channel": "军团",
        "chat_type": "发言",
        "risk_level": None,
        "risk_type": None,
        "risk_reason": None,
        "source_event": "role_chat",
    }


def test_replace_window_keeps_game_chat_separate_and_tracks_coverage(tmp_path) -> None:
    db_path = tmp_path / "monitor.db"
    init_database(db_path)
    repository = GameChatRepository(db_path)

    repository.replace_window(
        24,
        "2026-09-01",
        "2026-09-07",
        [
            _message("a", "2026-09-01 10:00:00.000"),
            _message("b", "2026-09-05 11:00:00.000", server_id="2"),
        ],
        started_at="2026-09-08T00:00:00+00:00",
        finished_at="2026-09-08T00:01:00+00:00",
        source_row_count=2,
        active_role_count=224,
    )

    rows = repository.list_messages(24, "2026-09-01", "2026-09-07")
    covering = repository.get_covering_success(24, "2026-09-02", "2026-09-05")

    assert [row["message_key"] for row in rows] == ["b", "a"]
    assert covering is not None
    assert covering["active_role_count"] == 224


def test_successful_empty_refresh_clears_only_the_requested_window(tmp_path) -> None:
    db_path = tmp_path / "monitor.db"
    init_database(db_path)
    repository = GameChatRepository(db_path)
    common = {
        "started_at": "2026-09-08T00:00:00+00:00",
        "finished_at": "2026-09-08T00:01:00+00:00",
        "source_row_count": 2,
        "active_role_count": 224,
    }
    repository.replace_window(
        24,
        "2026-09-01",
        "2026-09-10",
        [
            _message("inside", "2026-09-05 10:00:00.000"),
            _message("outside", "2026-09-09 10:00:00.000"),
        ],
        **common,
    )
    repository.replace_window(
        24,
        "2026-09-04",
        "2026-09-06",
        [],
        **{**common, "source_row_count": 0},
    )

    rows = repository.list_messages(24, "2026-09-01", "2026-09-10")
    assert [row["message_key"] for row in rows] == ["outside"]


def test_s25_filter_and_ranking_include_cached_s26_s27_without_rewriting_source(tmp_path) -> None:
    db_path = tmp_path / "monitor.db"
    init_database(db_path)
    repository = GameChatRepository(db_path)
    repository.replace_window(
        24,
        "2026-09-17",
        "2026-09-19",
        [
            _message("s25", "2026-09-19 10:00:00.000", server_id="25"),
            _message("s26", "2026-09-17 10:00:00.000", server_id="26"),
            _message("s27", "2026-09-18 10:00:00.000", server_id="27"),
        ],
        started_at="2026-09-20T00:00:00+00:00",
        finished_at="2026-09-20T00:01:00+00:00",
        source_row_count=3,
        active_role_count=3,
    )

    rows = repository.list_messages(24, "2026-09-17", "2026-09-19", server_ids=["25"])
    servers = repository.list_servers(24, "2026-09-17", "2026-09-19")

    assert len(rows) == 3
    assert {(row["server_id"], row["server_name"]) for row in rows} == {("25", "S25")}
    assert servers == [{"server_id": "25", "server_name": "S25", "message_count": 3}]
    with sqlite3.connect(db_path) as connection:
        raw_servers = connection.execute(
            "SELECT server_id FROM game_chat_messages ORDER BY message_key"
        ).fetchall()
    assert raw_servers == [("25",), ("26",), ("27",)]
