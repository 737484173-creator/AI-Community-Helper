from __future__ import annotations

import json
from datetime import datetime
from urllib import error, parse, request

from app.bot.direct_messenger import DISCORD_API_BASE


class DiscordMemberModerator:
    def __init__(
        self,
        bot_token: str,
        api_base: str = DISCORD_API_BASE,
        proxy: str | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.api_base = api_base.rstrip("/")
        self.proxy = proxy

    def timeout_member(
        self,
        guild_id: str,
        discord_user_id: str,
        until: datetime,
        reason: str,
    ) -> None:
        self._request(
            "PATCH",
            f"/guilds/{guild_id}/members/{discord_user_id}",
            {"communication_disabled_until": until.isoformat(timespec="seconds")},
            reason,
        )

    def kick_member(self, guild_id: str, discord_user_id: str, reason: str) -> None:
        self._request(
            "DELETE",
            f"/guilds/{guild_id}/members/{discord_user_id}",
            None,
            reason,
        )

    def ban_member(self, guild_id: str, discord_user_id: str, reason: str) -> None:
        self._request(
            "PUT",
            f"/guilds/{guild_id}/bans/{discord_user_id}",
            {"delete_message_seconds": 0},
            reason,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None,
        reason: str,
    ) -> None:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "User-Agent": "AI-Community-Operation-Center/1.0",
            "X-Audit-Log-Reason": parse.quote(reason, safe=""),
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        http_request = request.Request(
            f"{self.api_base}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            handlers = (
                [request.ProxyHandler({"http": self.proxy, "https": self.proxy})]
                if self.proxy
                else []
            )
            opener = request.build_opener(*handlers)
            with opener.open(http_request, timeout=20):
                return
        except error.HTTPError as exc:
            response_message = "Discord 拒绝了该操作"
            try:
                payload = json.loads(exc.read().decode("utf-8", errors="replace"))
                response_message = str(payload.get("message") or response_message)
            except (ValueError, AttributeError):
                pass
            raise RuntimeError(
                f"Discord 成员管理失败（HTTP {exc.code}）：{response_message}。"
                "请检查 Bot 权限和角色层级。"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"无法连接 Discord 成员管理接口：{exc.reason}") from exc
