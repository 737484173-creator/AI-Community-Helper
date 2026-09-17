from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, parse, request


@dataclass(frozen=True)
class DiscordActionResult:
    success: bool
    detail: str
    nickname_updated: bool = False


@dataclass(frozen=True)
class DiscordJoinRequest:
    request_id: str
    guild_id: str
    user_id: str
    username: str
    display_name: str | None
    raw_application: str
    created_at: str | None


class MemberReviewDiscordAdapter:
    def __init__(
        self,
        bot_token: str | None = None,
        proxy: str | None = None,
        api_base: str = "https://discord.com/api/v10",
    ) -> None:
        self.bot_token = bot_token
        self.proxy = proxy
        self.api_base = api_base.rstrip("/")

    def list_bot_guild_ids(self) -> list[str]:
        payload = self._request_json("GET", "/users/@me/guilds")
        return [str(guild["id"]) for guild in payload if guild.get("id")]

    def list_pending_join_requests(self, guild_id: str, page_limit: int = 100) -> list[DiscordJoinRequest]:
        requests: list[DiscordJoinRequest] = []
        before: str | None = None
        while True:
            query = {"status": "SUBMITTED", "limit": str(page_limit)}
            if before:
                query["before"] = before
            payload = self._request_json(
                "GET",
                f"/guilds/{guild_id}/requests?{parse.urlencode(query)}",
            )
            items = payload.get("guild_join_requests", [])
            if not items:
                break
            requests.extend(self._parse_join_request(item) for item in items)
            if len(items) < page_limit:
                break
            before = str(items[-1]["id"])
        return requests

    def _parse_join_request(self, item: dict) -> DiscordJoinRequest:
        user = item.get("user") or {}
        form_responses = item.get("form_responses") or []
        answers = [
            str(response.get("response") or "").strip()
            for response in form_responses
            if str(response.get("response") or "").strip()
        ]
        username = (
            user.get("global_name")
            or user.get("username")
            or item.get("user_id")
            or "Unknown"
        )
        return DiscordJoinRequest(
            request_id=str(item.get("id") or item.get("join_request_id") or ""),
            guild_id=str(item.get("guild_id") or ""),
            user_id=str(item.get("user_id") or user.get("id") or ""),
            username=str(username),
            display_name=user.get("global_name") or user.get("username"),
            raw_application="\n".join(answers) or str(username),
            created_at=item.get("created_at"),
        )

    def reject_join_request(self, guild_id: str, request_id: str, rejection_reason: str) -> DiscordActionResult:
        self._request_json(
            "PATCH",
            f"/guilds/{guild_id}/requests/{request_id}",
            {
                "action": "REJECTED",
                "rejection_reason": rejection_reason[:160],
            },
        )
        return DiscordActionResult(
            success=True,
            detail=f"Discord join request {request_id} rejected.",
            nickname_updated=False,
        )

    def approve_join_request(
        self,
        guild_id: str,
        request_id: str,
        discord_user_id: str,
        nickname: str | None,
    ) -> DiscordActionResult:
        self._request_json(
            "PATCH",
            f"/guilds/{guild_id}/requests/{request_id}",
            {"action": "APPROVED"},
        )
        nickname_updated = False
        nickname_detail = ""
        if nickname:
            try:
                self._request_json(
                    "PATCH",
                    f"/guilds/{guild_id}/members/{discord_user_id}",
                    {"nick": nickname[:32]},
                )
                nickname_updated = True
                nickname_detail = " Nickname updated."
            except RuntimeError as exc:
                nickname_detail = f" Nickname update failed: {exc}"
        return DiscordActionResult(
            success=True,
            detail=f"Discord join request {request_id} approved.{nickname_detail}",
            nickname_updated=nickname_updated,
        )

    def find_pending_join_request(self, discord_user_id: str) -> DiscordJoinRequest | None:
        for guild_id in self.list_bot_guild_ids():
            for join_request in self.list_pending_join_requests(guild_id):
                if join_request.user_id == discord_user_id:
                    return join_request
        return None

    def _request_json(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        if not self.bot_token:
            raise RuntimeError("DISCORD_BOT_TOKEN is required for Discord member review sync.")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        http_request = request.Request(
            f"{self.api_base}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bot {self.bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (AIDC, 1.0)",
            },
        )
        opener = request.build_opener(
            request.ProxyHandler({"http": self.proxy, "https": self.proxy})
        ) if self.proxy else request
        try:
            with opener.open(http_request, timeout=30) as response:
                raw_body = response.read().decode("utf-8")
                return json.loads(raw_body) if raw_body else {}
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord member review API error {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Discord member review API connection failed: {exc.reason}") from exc

    def approve_application(self, application_id: int, discord_user_id: str, nickname: str | None) -> DiscordActionResult:
        join_request = self.find_pending_join_request(discord_user_id)
        if join_request is None:
            return DiscordActionResult(
                success=False,
                detail="No pending Discord join request was found for this user.",
                nickname_updated=False,
            )
        return self.approve_join_request(
            join_request.guild_id,
            join_request.request_id,
            discord_user_id,
            nickname,
        )

    def reject_application(self, application_id: int, discord_user_id: str, rejection_reason: str) -> DiscordActionResult:
        join_request = self.find_pending_join_request(discord_user_id)
        if join_request is None:
            return DiscordActionResult(
                success=False,
                detail="No pending Discord join request was found for this user.",
                nickname_updated=False,
            )
        return self.reject_join_request(
            join_request.guild_id,
            join_request.request_id,
            rejection_reason,
        )
