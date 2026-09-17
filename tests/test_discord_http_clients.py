from __future__ import annotations

import json

from app.bot.direct_messenger import DiscordDirectMessenger
from app.bot.discord_identity import DiscordIdentityClient
from app.bot.member_moderator import DiscordMemberModerator


class FakeResponse:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class QueueOpener:
    def __init__(self, responses: list[dict | None]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple] = []

    def open(self, http_request, timeout: int):
        self.requests.append((http_request, timeout))
        return FakeResponse(self.responses.pop(0))


def test_identity_client_uses_an_opener_without_proxy(monkeypatch) -> None:
    opener = QueueOpener([{"global_name": "Saris", "username": "fallback"}])
    monkeypatch.setattr(
        "app.bot.discord_identity.request.build_opener",
        lambda *handlers: opener,
    )

    result = DiscordIdentityClient("token").fetch_display_name("user-1")

    assert result == "Saris"
    assert opener.requests[0][0].full_url.endswith("/users/user-1")


def test_direct_messenger_uses_an_opener_without_proxy(monkeypatch) -> None:
    opener = QueueOpener([{"id": "dm-1"}, {"id": "message-1"}])
    monkeypatch.setattr(
        "app.bot.direct_messenger.request.build_opener",
        lambda *handlers: opener,
    )

    result = DiscordDirectMessenger("token").send_dm("user-1", "hello")

    assert (result.channel_id, result.message_id) == ("dm-1", "message-1")
    assert [item[0].get_method() for item in opener.requests] == ["POST", "POST"]


def test_direct_messenger_can_send_to_existing_channel(monkeypatch) -> None:
    opener = QueueOpener([{"id": "message-2"}])
    monkeypatch.setattr(
        "app.bot.direct_messenger.request.build_opener",
        lambda *handlers: opener,
    )

    result = DiscordDirectMessenger("token").send_channel_message("thread-1", "hello")

    http_request = opener.requests[0][0]
    assert (result.channel_id, result.message_id) == ("thread-1", "message-2")
    assert http_request.get_method() == "POST"
    assert http_request.full_url.endswith("/channels/thread-1/messages")
    assert json.loads(http_request.data) == {"content": "hello"}


def test_member_moderator_builds_discord_timeout_request_without_proxy(monkeypatch) -> None:
    opener = QueueOpener([None])
    monkeypatch.setattr(
        "app.bot.member_moderator.request.build_opener",
        lambda *handlers: opener,
    )

    from datetime import datetime, timezone

    DiscordMemberModerator("token").timeout_member(
        "guild-1",
        "user-1",
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        "AIDC test reason",
    )

    http_request = opener.requests[0][0]
    assert http_request.get_method() == "PATCH"
    assert http_request.full_url.endswith("/guilds/guild-1/members/user-1")
    assert json.loads(http_request.data)["communication_disabled_until"] == "2026-09-03T00:00:00+00:00"
    assert http_request.headers["X-audit-log-reason"] == "AIDC%20test%20reason"
