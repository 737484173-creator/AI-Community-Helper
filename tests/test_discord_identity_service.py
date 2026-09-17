from __future__ import annotations

from pathlib import Path

from app.dashboard.discord_identity_service import DiscordIdentityService
from app.database.migrations.init_db import init_database
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.user_repository import UserRepository


class FakeIdentityClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def fetch_display_name(self, discord_user_id: str, guild_id: str | None = None) -> str:
        self.calls.append((discord_user_id, guild_id))
        return "Blak [S12 > S11]"


def test_identity_service_fetches_then_persists_discord_display_name(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    client = FakeIdentityClient()
    service = DiscordIdentityService(db_path, client=client)

    first = service.resolve_display_name("139426580438056960", "guild-1")
    second = service.resolve_display_name("139426580438056960", "guild-1")

    assert first == "Blak [S12 > S11]"
    assert second == first
    assert client.calls == [("139426580438056960", "guild-1")]
    stored = UserRepository(db_path).get_by_discord_id("139426580438056960")
    assert stored is not None
    assert stored["discord_user_name"] == "Blak [S12 > S11]"


def test_chat_message_query_includes_cached_name_and_guild(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    UserRepository(db_path).get_or_create("user-1", discord_user_name="Saris")
    DiscordChannelRepository(db_path).upsert(
        "channel-1",
        "game-chat",
        "TextChannel",
        "guild-1",
    )
    MessageRepository(db_path).create(
        discord_user_id="user-1",
        channel_id="channel-1",
        message="hello",
    )

    rows = MessageRepository(db_path).list_channels_messages_between(
        "2000-01-01 00:00:00",
        "2099-01-01 00:00:00",
        ("game-chat",),
    )

    assert rows[0]["discord_user_name"] == "Saris"
    assert rows[0]["guild_id"] == "guild-1"
