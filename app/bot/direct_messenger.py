from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, request


DISCORD_API_BASE = "https://discord.com/api/v10"


@dataclass(frozen=True)
class DiscordSendResult:
    channel_id: str
    message_id: str


class DiscordDirectMessenger:
    def __init__(
        self,
        bot_token: str,
        api_base: str = DISCORD_API_BASE,
        proxy: str | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.api_base = api_base.rstrip("/")
        self.proxy = proxy

    def send_dm(self, discord_user_id: str, content: str) -> DiscordSendResult:
        dm_channel = self._request_json(
            "POST",
            "/users/@me/channels",
            {"recipient_id": discord_user_id},
        )
        message = self._request_json(
            "POST",
            f"/channels/{dm_channel['id']}/messages",
            {"content": content},
        )
        return DiscordSendResult(
            channel_id=str(dm_channel["id"]),
            message_id=str(message["id"]),
        )

    def send_channel_message(self, channel_id: str, content: str) -> DiscordSendResult:
        message = self._request_json(
            "POST",
            f"/channels/{channel_id}/messages",
            {"content": content},
        )
        return DiscordSendResult(
            channel_id=channel_id,
            message_id=str(message["id"]),
        )

    def _request_json(self, method: str, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self.api_base}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bot {self.bot_token}",
                "Content-Type": "application/json",
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
            with opener.open(http_request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord API error {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Discord API connection failed: {exc.reason}") from exc
