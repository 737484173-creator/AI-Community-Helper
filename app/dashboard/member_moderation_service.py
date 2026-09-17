from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.bot.member_moderator import DiscordMemberModerator
from config.settings import get_settings


ACTION_TIMEOUT = "TIMEOUT"
ACTION_KICK = "KICK"
ACTION_BAN = "BAN"
ACTION_LABELS = {
    ACTION_TIMEOUT: "禁言",
    ACTION_KICK: "踢出服务器",
    ACTION_BAN: "封禁成员",
}
TIMEOUT_OPTIONS = {
    "10 分钟": 10,
    "1 小时": 60,
    "24 小时": 24 * 60,
    "7 天": 7 * 24 * 60,
    "28 天": 28 * 24 * 60,
}


class MemberModerator(Protocol):
    def timeout_member(
        self,
        guild_id: str,
        discord_user_id: str,
        until: datetime,
        reason: str,
    ) -> None: ...

    def kick_member(self, guild_id: str, discord_user_id: str, reason: str) -> None: ...

    def ban_member(self, guild_id: str, discord_user_id: str, reason: str) -> None: ...


@dataclass(frozen=True)
class ModerationResult:
    action: str
    action_label: str
    discord_user_id: str
    timeout_until: datetime | None = None


class MemberModerationService:
    def __init__(self, moderator: MemberModerator | None = None) -> None:
        if moderator is not None:
            self.moderator = moderator
            return
        settings = get_settings()
        if not settings.discord_bot_token:
            raise RuntimeError("缺少 DISCORD_BOT_TOKEN，无法管理 Discord 成员。")
        self.moderator = DiscordMemberModerator(
            settings.discord_bot_token,
            proxy=settings.discord_proxy,
        )

    def moderate(
        self,
        guild_id: str,
        discord_user_id: str,
        action: str,
        reason: str,
        timeout_minutes: int | None = None,
    ) -> ModerationResult:
        clean_guild_id = guild_id.strip()
        clean_user_id = discord_user_id.strip()
        clean_reason = reason.strip()
        if not clean_guild_id:
            raise ValueError("当前记录缺少 Discord 服务器 ID，无法执行成员管理。")
        if not clean_user_id:
            raise ValueError("当前记录缺少 Discord 用户 ID，无法执行成员管理。")
        if action not in ACTION_LABELS:
            raise ValueError("不支持的 Discord 成员管理动作。")
        if not clean_reason:
            raise ValueError("请填写成员管理原因，该原因会写入 Discord 审核日志。")
        if len(clean_reason) > 512:
            raise ValueError("成员管理原因不能超过 512 个字符。")

        if action == ACTION_TIMEOUT:
            if timeout_minutes is None or not 1 <= timeout_minutes <= 28 * 24 * 60:
                raise ValueError("Discord 禁言时长必须在 1 分钟到 28 天之间。")
            timeout_until = datetime.now(timezone.utc) + timedelta(minutes=timeout_minutes)
            self.moderator.timeout_member(
                clean_guild_id,
                clean_user_id,
                timeout_until,
                clean_reason,
            )
            return ModerationResult(
                action=action,
                action_label=ACTION_LABELS[action],
                discord_user_id=clean_user_id,
                timeout_until=timeout_until,
            )

        if action == ACTION_KICK:
            self.moderator.kick_member(clean_guild_id, clean_user_id, clean_reason)
        else:
            self.moderator.ban_member(clean_guild_id, clean_user_id, clean_reason)
        return ModerationResult(
            action=action,
            action_label=ACTION_LABELS[action],
            discord_user_id=clean_user_id,
        )
