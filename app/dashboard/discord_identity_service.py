from __future__ import annotations

from pathlib import Path

from app.bot.discord_identity import DiscordIdentityClient
from app.database.repositories.user_repository import UserRepository
from config.settings import get_settings


class DiscordIdentityService:
    def __init__(
        self,
        db_path: str | Path,
        client: DiscordIdentityClient | None = None,
    ) -> None:
        self.users = UserRepository(db_path)
        if client is not None:
            self.client = client
            return
        settings = get_settings()
        self.client = (
            DiscordIdentityClient(
                settings.discord_bot_token,
                proxy=settings.discord_proxy,
            )
            if settings.discord_bot_token
            else None
        )

    def resolve_display_name(
        self,
        discord_user_id: str,
        guild_id: str | None = None,
    ) -> str | None:
        clean_user_id = discord_user_id.strip()
        if not clean_user_id:
            return None

        cached = self.users.get_by_discord_id(clean_user_id)
        if cached:
            cached_name = str(cached["discord_user_name"] or "").strip()
            if cached_name:
                return cached_name

        if self.client is None:
            return None

        display_name = self.client.fetch_display_name(clean_user_id, guild_id)
        if not display_name:
            return None
        self.users.get_or_create(
            clean_user_id,
            discord_user_name=display_name,
        )
        return display_name
