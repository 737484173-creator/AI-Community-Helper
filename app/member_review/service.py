from __future__ import annotations

from dataclasses import dataclass

from app.database.repositories.member_review_repository import MemberReviewRepository
from app.member_review.config_loader import load_review_rules, load_server_mapping
from app.member_review.discord_adapter import DiscordActionResult, DiscordJoinRequest, MemberReviewDiscordAdapter
from app.member_review.messages import generate_rejection_reason
from app.member_review.parser import parse_member_application
from config.settings import get_settings


@dataclass(frozen=True)
class MemberReviewResult:
    application_id: int
    status: str
    detail: str
    discord_result: DiscordActionResult


class MemberReviewService:
    def __init__(
        self,
        db_path=None,
        adapter: MemberReviewDiscordAdapter | None = None,
    ) -> None:
        self.repository = MemberReviewRepository(db_path)
        settings = get_settings()
        self.adapter = adapter or MemberReviewDiscordAdapter(
            bot_token=settings.discord_bot_token,
            proxy=settings.discord_proxy,
        )
        self.server_mapping = load_server_mapping()
        self.rules = load_review_rules()

    def ingest_manual_application(
        self,
        *,
        discord_username: str,
        discord_user_id: str,
        raw_application: str,
    ) -> int:
        parsed = parse_member_application(raw_application, self.server_mapping)
        rejection_reason = None if parsed.status == "可通过" else generate_rejection_reason(parsed.reason_code)
        auto_approvable = (
            parsed.status == "可通过"
            and parsed.confidence >= float(self.rules.get("minimum_auto_approve_confidence", 0.95))
            and bool(self.rules.get("auto_approve_enabled", False))
        )
        return self.repository.create_application(
            discord_username=discord_username,
            discord_user_id=discord_user_id,
            raw_application=raw_application,
            player_name=parsed.player_name,
            server_id=parsed.server_id,
            raw_server_input=parsed.raw_server_input,
            server_name=parsed.server_name,
            discord_nickname=parsed.discord_nickname,
            review_status=parsed.status,
            reason_code=parsed.reason_code,
            internal_reason=parsed.internal_reason,
            rejection_reason=rejection_reason,
            confidence=parsed.confidence,
            auto_approvable=auto_approvable,
        )

    def ingest_discord_pending_member(
        self,
        *,
        discord_username: str,
        discord_user_id: str,
        raw_application: str | None = None,
    ) -> int:
        application_text = (raw_application or discord_username or discord_user_id).strip()
        parsed = parse_member_application(application_text, self.server_mapping)
        internal_reason = (
            f"{parsed.internal_reason}；来自 Discord 待定成员同步，原生申请表答案当前无法通过 Bot API 直接读取。"
        )
        rejection_reason = None if parsed.status == "可通过" else generate_rejection_reason(parsed.reason_code)
        auto_approvable = (
            parsed.status == "可通过"
            and parsed.confidence >= float(self.rules.get("minimum_auto_approve_confidence", 0.95))
            and bool(self.rules.get("auto_approve_enabled", False))
        )
        existing = self.repository.get_open_by_discord_user_id(discord_user_id)
        if existing is not None:
            application_id = int(existing["id"])
            self.repository.update_open_application(
                application_id=application_id,
                discord_username=discord_username,
                raw_application=application_text,
                player_name=parsed.player_name,
                server_id=parsed.server_id,
                raw_server_input=parsed.raw_server_input,
                server_name=parsed.server_name,
                discord_nickname=parsed.discord_nickname,
                review_status=parsed.status,
                reason_code=parsed.reason_code,
                internal_reason=internal_reason,
                rejection_reason=rejection_reason,
                confidence=parsed.confidence,
                auto_approvable=auto_approvable,
            )
            return application_id

        return self.repository.create_application(
            discord_username=discord_username,
            discord_user_id=discord_user_id,
            raw_application=application_text,
            player_name=parsed.player_name,
            server_id=parsed.server_id,
            raw_server_input=parsed.raw_server_input,
            server_name=parsed.server_name,
            discord_nickname=parsed.discord_nickname,
            review_status=parsed.status,
            reason_code=parsed.reason_code,
            internal_reason=internal_reason,
            rejection_reason=rejection_reason,
            confidence=parsed.confidence,
            auto_approvable=auto_approvable,
        )

    def sync_discord_join_requests(self, guild_ids: list[str] | None = None) -> int:
        target_guild_ids = guild_ids or self.adapter.list_bot_guild_ids()
        synced = 0
        for guild_id in target_guild_ids:
            for join_request in self.adapter.list_pending_join_requests(str(guild_id)):
                self.ingest_discord_join_request(join_request)
                synced += 1
        return synced

    def ingest_discord_join_request(self, join_request: DiscordJoinRequest) -> int:
        application_id = self.ingest_discord_pending_member(
            discord_username=join_request.display_name or join_request.username,
            discord_user_id=join_request.user_id,
            raw_application=join_request.raw_application,
        )
        row = self.repository.get(application_id)
        if row is None:
            return application_id

        if row["review_status"] in {"信息不完整", "区服ID异常"}:
            rejection_reason = row["rejection_reason"] or generate_rejection_reason(row["reason_code"])
            discord_result = self.adapter.reject_join_request(
                join_request.guild_id,
                join_request.request_id,
                rejection_reason,
            )
            self.repository.update_review_result(
                application_id=application_id,
                review_status="已拒绝",
                final_result="拒绝",
                rejection_reason=rejection_reason,
                nickname_result=None,
                discord_api_result=discord_result.detail,
                reviewer="Discord Auto Review",
            )
            self._log(
                row,
                "拒绝",
                rejection_reason,
                "Discord Auto Review",
                None,
                discord_result.detail,
            )
        elif bool(row["auto_approvable"]):
            discord_result = self.adapter.approve_join_request(
                join_request.guild_id,
                join_request.request_id,
                join_request.user_id,
                row["discord_nickname"],
            )
            self._record_approval(row, discord_result, reviewer="Discord Auto Review")
        return application_id

    def approve(self, application_id: int, reviewer: str | None = None) -> MemberReviewResult:
        row = self.repository.get(application_id)
        if row is None:
            raise ValueError(f"Application #{application_id} does not exist")
        if row["review_status"] not in {"可通过", "需要人工审核"}:
            raise ValueError("Only passable or manually reviewed applications can be approved")
        discord_result = self.adapter.approve_application(
            application_id,
            str(row["discord_user_id"]),
            row["discord_nickname"],
        )
        self._record_approval(row, discord_result, reviewer=reviewer)
        return MemberReviewResult(application_id, "已通过", "审核已记录；如 Discord API 未接入，请手动批准并复制昵称。", discord_result)

    def _record_approval(
        self,
        row,
        discord_result: DiscordActionResult,
        *,
        reviewer: str | None,
    ) -> None:
        application_id = int(row["id"])
        nickname_result = "昵称修改成功" if discord_result.nickname_updated else "未执行或需人工修改昵称"
        self.repository.update_review_result(
            application_id=application_id,
            review_status="已通过",
            final_result="通过",
            rejection_reason=None,
            nickname_result=nickname_result,
            discord_api_result=discord_result.detail,
            reviewer=reviewer,
        )
        self._log(row, "通过", None, reviewer, nickname_result, discord_result.detail)

    def reject(self, application_id: int, rejection_reason: str, reviewer: str | None = None) -> MemberReviewResult:
        row = self.repository.get(application_id)
        if row is None:
            raise ValueError(f"Application #{application_id} does not exist")
        discord_result = self.adapter.reject_application(
            application_id,
            str(row["discord_user_id"]),
            rejection_reason,
        )
        self.repository.update_review_result(
            application_id=application_id,
            review_status="已拒绝",
            final_result="拒绝",
            rejection_reason=rejection_reason,
            nickname_result=None,
            discord_api_result=discord_result.detail,
            reviewer=reviewer,
        )
        self._log(row, "拒绝", rejection_reason, reviewer, None, discord_result.detail)
        return MemberReviewResult(application_id, "已拒绝", "拒绝结果已记录；如 Discord API 未接入，请手动发送英文理由。", discord_result)

    def _log(
        self,
        row,
        final_result: str,
        rejection_reason: str | None,
        reviewer: str | None,
        nickname_result: str | None,
        discord_api_result: str | None,
    ) -> None:
        self.repository.create_log(
            application_id=int(row["id"]),
            discord_username=row["discord_username"],
            discord_user_id=row["discord_user_id"],
            raw_application=row["raw_application"],
            player_name=row["player_name"],
            server_id=row["server_id"],
            server_name=row["server_name"],
            discord_nickname=row["discord_nickname"],
            system_status=row["review_status"],
            final_result=final_result,
            rejection_reason=rejection_reason,
            reviewer=reviewer,
            nickname_result=nickname_result,
            discord_api_result=discord_api_result,
        )
