from __future__ import annotations

import pytest

from app.database.migrations.init_db import init_database
from app.database.repositories.member_review_repository import MemberReviewRepository
from app.member_review.discord_adapter import DiscordActionResult, DiscordJoinRequest
from app.member_review.messages import generate_rejection_reason
from app.member_review.nickname_formatter import generate_discord_nickname, normalize_server_id
from app.member_review.parser import parse_member_application
from app.member_review.service import MemberReviewService


SERVER_MAPPING = {"1": "S1", "6": "S6", "11": "S11", "14": "S14"}


@pytest.mark.parametrize(
    ("raw_text", "player_name", "server_id", "nickname"),
    [
        ("14 Bubble", "Bubble", "14", "S14 Bubble"),
        ("S14 Bubble", "Bubble", "14", "S14 Bubble"),
        ("s14 Bubble", "Bubble", "14", "S14 Bubble"),
        ("Bubble 14", "Bubble", "14", "S14 Bubble"),
        ("Bubble S14", "Bubble", "14", "S14 Bubble"),
        ("Bubble s14", "Bubble", "14", "S14 Bubble"),
        ("14 / Bubble", "Bubble", "14", "S14 Bubble"),
        ("S14 / Bubble", "Bubble", "14", "S14 Bubble"),
        ("Bubble / 14", "Bubble", "14", "S14 Bubble"),
        ("Bubble / S14", "Bubble", "14", "S14 Bubble"),
        ("14 - Bubble", "Bubble", "14", "S14 Bubble"),
        ("S14 - Bubble", "Bubble", "14", "S14 Bubble"),
        ("角色名：Bubble 区服：14", "Bubble", "14", "S14 Bubble"),
        ("角色名：Bubble 区服：S14", "Bubble", "14", "S14 Bubble"),
        ("Name: Bubble Server: 14", "Bubble", "14", "S14 Bubble"),
        ("Name: Bubble Server: S14", "Bubble", "14", "S14 Bubble"),
        ("Server ID: 14 Name: Bubble", "Bubble", "14", "S14 Bubble"),
        ("Server ID: S14 Name: Bubble", "Bubble", "14", "S14 Bubble"),
        ("S14 Bubble King", "Bubble King", "14", "S14 Bubble King"),
        ("14 Bubble King", "Bubble King", "14", "S14 Bubble King"),
        ("S14 Player2026", "Player2026", "14", "S14 Player2026"),
    ],
)
def test_member_application_parser_accepts_valid_formats(raw_text, player_name, server_id, nickname) -> None:
    parsed = parse_member_application(raw_text, SERVER_MAPPING)

    assert parsed.status == "可通过"
    assert parsed.player_name == player_name
    assert parsed.server_id == server_id
    assert parsed.server_name == f"S{server_id}"
    assert parsed.discord_nickname == nickname


@pytest.mark.parametrize(
    ("raw_text", "status", "reason_code"),
    [
        ("14", "信息不完整", "MISSING_PLAYER_NAME"),
        ("S14", "信息不完整", "MISSING_PLAYER_NAME"),
        ("Bubble", "信息不完整", "MISSING_SERVER_ID"),
        ("", "信息不完整", "INCOMPLETE_APPLICATION"),
        ("Hello I want to join", "信息不完整", "MISSING_SERVER_ID"),
        ("S999 Bubble", "区服ID异常", "INVALID_SERVER_ID"),
        ("999 Bubble", "区服ID异常", "INVALID_SERVER_ID"),
        ("S11 S14 Bubble", "需要人工审核", "MULTIPLE_SERVER_IDS"),
        ("11 14 Bubble", "需要人工审核", "MULTIPLE_SERVER_IDS"),
        ("Player2026", "信息不完整", "MISSING_SERVER_ID"),
    ],
)
def test_member_application_parser_rejects_or_flags_invalid_formats(raw_text, status, reason_code) -> None:
    parsed = parse_member_application(raw_text, SERVER_MAPPING)

    assert parsed.status == status
    assert parsed.reason_code == reason_code


def test_nickname_helpers_normalize_server_id() -> None:
    assert normalize_server_id("14") == "14"
    assert normalize_server_id("S14") == "14"
    assert normalize_server_id("s14") == "14"
    assert generate_discord_nickname("14", "Bubble King", SERVER_MAPPING) == "S14 Bubble King"


def test_rejection_reason_is_english() -> None:
    reason = generate_rejection_reason("MISSING_SERVER_ID")

    assert "server ID" in reason
    assert "S14 Bubble" in reason


class FakeManualActionAdapter:
    def approve_application(self, application_id: int, discord_user_id: str, nickname: str | None):
        return DiscordActionResult(True, "Approved in fake adapter.", nickname_updated=bool(nickname))

    def reject_application(self, application_id: int, discord_user_id: str, rejection_reason: str):
        return DiscordActionResult(True, "Rejected in fake adapter.")


def test_member_review_service_records_approval_log(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    service = MemberReviewService(db_path, adapter=FakeManualActionAdapter())
    application_id = service.ingest_manual_application(
        discord_username="BubbleUser",
        discord_user_id="1001",
        raw_application="S14 Bubble",
    )

    result = service.approve(application_id, reviewer="Admin")
    row = MemberReviewRepository(db_path).get(application_id)
    logs = MemberReviewRepository(db_path).list_logs()

    assert result.status == "已通过"
    assert row["review_status"] == "已通过"
    assert row["processed"] == 1
    assert logs[0]["final_result"] == "通过"
    assert logs[0]["discord_nickname"] == "S14 Bubble"


def test_member_review_service_records_rejection_log(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    service = MemberReviewService(db_path, adapter=FakeManualActionAdapter())
    application_id = service.ingest_manual_application(
        discord_username="BubbleUser",
        discord_user_id="1001",
        raw_application="Bubble",
    )

    reason = generate_rejection_reason("MISSING_SERVER_ID")
    result = service.reject(application_id, rejection_reason=reason, reviewer="Admin")
    logs = MemberReviewRepository(db_path).list_logs()

    assert result.status == "已拒绝"
    assert logs[0]["final_result"] == "拒绝"
    assert logs[0]["rejection_reason"] == reason


def test_member_review_service_updates_existing_pending_member(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    service = MemberReviewService(db_path)

    first_id = service.ingest_discord_pending_member(
        discord_username="BubbleUser",
        discord_user_id="1001",
        raw_application="Bubble",
    )
    second_id = service.ingest_discord_pending_member(
        discord_username="BubbleUser",
        discord_user_id="1001",
        raw_application="S14 Bubble",
    )
    repository = MemberReviewRepository(db_path)
    rows = repository.list_filtered()

    assert second_id == first_id
    assert len(rows) == 1
    assert rows[0]["review_status"] == "可通过"
    assert rows[0]["discord_nickname"] == "S14 Bubble"


class FakeJoinRequestAdapter:
    def __init__(self, raw_application: str = "S14 Bubble") -> None:
        self.raw_application = raw_application
        self.approved_requests: list[tuple[str, str, str, str | None]] = []
        self.rejected_requests: list[tuple[str, str, str]] = []

    def list_bot_guild_ids(self) -> list[str]:
        return ["guild-1"]

    def list_pending_join_requests(self, guild_id: str) -> list[DiscordJoinRequest]:
        assert guild_id == "guild-1"
        return [
            DiscordJoinRequest(
                request_id="request-1",
                guild_id=guild_id,
                user_id="1001",
                username="BubbleUser",
                display_name="BubbleUser",
                raw_application=self.raw_application,
                created_at="2026-08-26T09:12:33.687000+00:00",
            )
        ]

    def approve_application(self, application_id: int, discord_user_id: str, nickname: str | None):
        raise AssertionError("approve should not be called during sync")

    def approve_join_request(
        self,
        guild_id: str,
        request_id: str,
        discord_user_id: str,
        nickname: str | None,
    ):
        self.approved_requests.append((guild_id, request_id, discord_user_id, nickname))
        return DiscordActionResult(True, f"Approved {request_id}. Nickname updated.", nickname_updated=True)

    def reject_application(self, application_id: int, discord_user_id: str, rejection_reason: str):
        raise AssertionError("reject should not be called during sync")

    def reject_join_request(self, guild_id: str, request_id: str, rejection_reason: str):
        self.rejected_requests.append((guild_id, request_id, rejection_reason))
        from app.member_review.discord_adapter import DiscordActionResult

        return DiscordActionResult(True, f"Rejected {request_id}")


def test_member_review_service_syncs_discord_join_requests(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    adapter = FakeJoinRequestAdapter()
    service = MemberReviewService(db_path, adapter=adapter)

    synced = service.sync_discord_join_requests()
    repository = MemberReviewRepository(db_path)
    rows = repository.list_filtered(processed_filter="已处理")
    logs = repository.list_logs()

    assert synced == 1
    assert len(rows) == 1
    assert adapter.approved_requests == [("guild-1", "request-1", "1001", "S14 Bubble")]
    assert rows[0]["discord_user_id"] == "1001"
    assert rows[0]["raw_application"] == "S14 Bubble"
    assert rows[0]["review_status"] == "已通过"
    assert rows[0]["final_result"] == "通过"
    assert rows[0]["nickname_result"] == "昵称修改成功"
    assert rows[0]["processed"] == 1
    assert logs[0]["reviewer"] == "Discord Auto Review"
    assert logs[0]["discord_nickname"] == "S14 Bubble"


def test_member_review_service_auto_rejects_incomplete_join_requests(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    adapter = FakeJoinRequestAdapter(raw_application="Bubble")
    service = MemberReviewService(db_path, adapter=adapter)

    synced = service.sync_discord_join_requests()
    rows = MemberReviewRepository(db_path).list_filtered(processed_filter="已处理")
    logs = MemberReviewRepository(db_path).list_logs()

    assert synced == 1
    assert len(adapter.rejected_requests) == 1
    assert rows[0]["review_status"] == "已拒绝"
    assert rows[0]["final_result"] == "拒绝"
    assert rows[0]["processed"] == 1
    assert "server ID" in rows[0]["rejection_reason"]
    assert logs[0]["reviewer"] == "Discord Auto Review"


def test_member_review_service_auto_rejects_invalid_server_join_requests(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    adapter = FakeJoinRequestAdapter(raw_application="S999 Bubble")
    service = MemberReviewService(db_path, adapter=adapter)

    synced = service.sync_discord_join_requests()
    rows = MemberReviewRepository(db_path).list_filtered(processed_filter="已处理")

    assert synced == 1
    assert len(adapter.rejected_requests) == 1
    assert rows[0]["review_status"] == "已拒绝"
    assert rows[0]["reason_code"] == "INVALID_SERVER_ID"
    assert "server ID" in rows[0]["rejection_reason"]
