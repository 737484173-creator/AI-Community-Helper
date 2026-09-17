from __future__ import annotations

from pathlib import Path

from app.database.db import db_session
from app.database.migrations.init_db import init_database
from app.database.repositories.user_repository import UserRepository
from app.database.repositories.vip_extension_repository import (
    PlayerProfileRepository,
    RiskProfileRepository,
    VIPProfileRepository,
)


def test_vip_extension_tables_are_created(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    with db_session(db_path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "player_profiles" in tables
    assert "vip_profiles" in tables
    assert "risk_profiles" in tables


def test_vip_extension_repositories_upsert_future_game_profiles(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    players = PlayerProfileRepository(db_path)
    vip = VIPProfileRepository(db_path)
    risk = RiskProfileRepository(db_path)

    players.upsert(
        player_id="player-1",
        server_id="server-1",
        display_name="Knight",
        last_login_time="2026-07-31 10:00:00",
        profile_json='{"class": "warrior"}',
    )
    vip.upsert(
        player_id="player-1",
        server_id="server-1",
        vip_level=5,
        total_payment_amount=199.99,
        last_payment_time="2026-07-31 09:00:00",
    )
    risk.upsert(
        player_id="player-1",
        server_id="server-1",
        risk_score=0.72,
        risk_level="Medium",
        risk_reason_json='["refund_request"]',
    )

    assert players.get("player-1", "server-1")["display_name"] == "Knight"
    assert vip.get("player-1", "server-1")["vip_level"] == 5
    assert risk.get("player-1", "server-1")["risk_level"] == "Medium"


def test_discord_user_is_not_auto_bound_to_player_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    user = UserRepository(db_path).get_or_create("discord-1")
    PlayerProfileRepository(db_path).upsert("player-1", "server-1")

    refreshed_user = UserRepository(db_path).get_by_discord_id(user["discord_user_id"])

    assert refreshed_user["player_id"] is None
    assert refreshed_user["server_id"] is None

