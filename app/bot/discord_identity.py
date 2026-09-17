from __future__ import annotations

import json
from urllib import error, request

from app.bot.direct_messenger import DISCORD_API_BASE


class DiscordIdentityClient:
    def __init__(
        self,
        bot_token: str,
        api_base: str = DISCORD_API_BASE,
        proxy: str | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.api_base = api_base.rstrip("/")
        self.proxy = proxy

    def fetch_display_name(self, discord_user_id: str, guild_id: str | None = None) -> str | None:
        if guild_id:
            try:
                member = self._request_json(f"/guilds/{guild_id}/members/{discord_user_id}")
            except RuntimeError:
                member = None
            if member:
                user = member.get("user") or {}
                name = member.get("nick") or user.get("global_name") or user.get("username")
                if name:
                    return str(name)

        user = self._request_json(f"/users/{discord_user_id}")
        name = user.get("global_name") or user.get("username")
        return str(name) if name else None

    def _request_json(self, path: str) -> dict:
        http_request = request.Request(
            f"{self.api_base}{path}",
            method="GET",
            headers={
                "Authorization": f"Bot {self.bot_token}",
                "User-Agent": "AI-Community-Operation-Center/1.0",
            },
        )
        try:
            handlers = (
                [request.ProxyHandler({"http": self.proxy, "https": self.proxy})]
                if self.proxy
                else []
            )
            opener = request.build_opener(*handlers)
            with opener.open(http_request, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RuntimeError(f"Discord identity lookup failed with HTTP {exc.code}.") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Discord identity lookup failed: {exc.reason}") from exc
