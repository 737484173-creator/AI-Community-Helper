from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.dashboard.member_moderation_service import (
    ACTION_BAN,
    ACTION_KICK,
    ACTION_TIMEOUT,
    MemberModerationService,
)


class FakeMemberModerator:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def timeout_member(
        self,
        guild_id: str,
        discord_user_id: str,
        until: datetime,
        reason: str,
    ) -> None:
        self.calls.append((ACTION_TIMEOUT, guild_id, discord_user_id, until, reason))

    def kick_member(self, guild_id: str, discord_user_id: str, reason: str) -> None:
        self.calls.append((ACTION_KICK, guild_id, discord_user_id, reason))

    def ban_member(self, guild_id: str, discord_user_id: str, reason: str) -> None:
        self.calls.append((ACTION_BAN, guild_id, discord_user_id, reason))


def test_timeout_member_uses_requested_duration_and_audit_reason() -> None:
    moderator = FakeMemberModerator()
    service = MemberModerationService(moderator)
    started_at = datetime.now(timezone.utc)

    result = service.moderate(" guild-1 ", " user-1 ", ACTION_TIMEOUT, " repeated abuse ", 60)

    action, guild_id, user_id, until, reason = moderator.calls[0]
    assert (action, guild_id, user_id, reason) == (
        ACTION_TIMEOUT,
        "guild-1",
        "user-1",
        "repeated abuse",
    )
    assert 59 * 60 <= (until - started_at).total_seconds() <= 61 * 60
    assert result.timeout_until == until
    assert result.action_label == "禁言"


@pytest.mark.parametrize(
    ("action", "expected_call", "expected_label"),
    [
        (ACTION_KICK, ACTION_KICK, "踢出服务器"),
        (ACTION_BAN, ACTION_BAN, "封禁成员"),
    ],
)
def test_kick_and_ban_call_the_matching_discord_operation(
    action: str,
    expected_call: str,
    expected_label: str,
) -> None:
    moderator = FakeMemberModerator()

    result = MemberModerationService(moderator).moderate(
        "guild-1",
        "user-1",
        action,
        "moderator decision",
    )

    assert moderator.calls == [(expected_call, "guild-1", "user-1", "moderator decision")]
    assert result.action_label == expected_label
    assert result.timeout_until is None


@pytest.mark.parametrize(
    ("guild_id", "user_id", "action", "reason", "minutes", "message"),
    [
        ("", "user-1", ACTION_KICK, "reason", None, "服务器 ID"),
        ("guild-1", "", ACTION_KICK, "reason", None, "用户 ID"),
        ("guild-1", "user-1", "UNKNOWN", "reason", None, "不支持"),
        ("guild-1", "user-1", ACTION_KICK, "   ", None, "填写成员管理原因"),
        ("guild-1", "user-1", ACTION_TIMEOUT, "reason", 0, "1 分钟到 28 天"),
        ("guild-1", "user-1", ACTION_TIMEOUT, "reason", 40321, "1 分钟到 28 天"),
    ],
)
def test_invalid_moderation_requests_are_rejected_before_discord_call(
    guild_id: str,
    user_id: str,
    action: str,
    reason: str,
    minutes: int | None,
    message: str,
) -> None:
    moderator = FakeMemberModerator()

    with pytest.raises(ValueError, match=message):
        MemberModerationService(moderator).moderate(
            guild_id,
            user_id,
            action,
            reason,
            minutes,
        )

    assert moderator.calls == []
