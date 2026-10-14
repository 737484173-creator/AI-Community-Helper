from __future__ import annotations

import json
from datetime import date

import pytest

from app.database.migrations.init_db import init_database
from app.database.repositories.member_review_repository import MemberReviewRepository
from app.member_review.config_loader import load_planned_server_dates, load_server_mapping
from app.member_review.discord_adapter import DiscordActionResult, DiscordJoinRequest
from app.member_review.messages import generate_rejection_reason
from app.member_review.nickname_formatter import generate_discord_nickname, normalize_server_id
from app.member_review.parser import parse_member_application
from app.member_review.service import MemberReviewService
from config.settings import BASE_DIR


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
    assert "S51 Bubble" in reason


def test_open_servers_are_contiguous_through_s51_on_september_20() -> None:
    server_mapping = load_server_mapping(as_of=date(2026, 9, 20))

    assert set(server_mapping) == {str(server_id) for server_id in range(1, 52)}
    assert server_mapping["11"] == "S11"
    assert server_mapping["12"] == "S11"


@pytest.mark.parametrize(
    ("source", "primary"),
    [
        ("2", "6"), ("3", "6"), ("4", "1"), ("5", "1"),
        ("7", "6"), ("8", "1"), ("9", "1"), ("10", "6"),
        ("12", "11"), ("13", "11"), ("15", "14"), ("16", "14"),
        ("17", "19"), ("18", "20"), ("21", "19"),
        ("22", "23"), ("24", "23"), ("26", "25"), ("27", "25"),
        ("29", "28"), ("30", "28"), ("32", "31"), ("33", "31"),
        ("34", "36"), ("35", "36"),
    ],
)
def test_merged_source_server_is_approved_as_primary(source: str, primary: str) -> None:
    parsed = parse_member_application(
        f"S{source} Bubble",
        load_server_mapping(as_of=date(2026, 9, 21)),
    )

    assert parsed.status == "可通过"
    assert parsed.reason_code == "PASS"
    assert parsed.server_id == primary
    assert parsed.server_name == f"S{primary}"
    assert parsed.raw_server_input == f"S{source}"
    assert parsed.discord_nickname == f"S{primary} Bubble"
    assert parsed.detected_server_ids == (source,)


def test_merged_source_still_requires_player_name() -> None:
    parsed = parse_member_application("S12", load_server_mapping(as_of=date(2026, 9, 21)))

    assert parsed.status == "信息不完整"
    assert parsed.reason_code == "MISSING_PLAYER_NAME"
    assert parsed.server_id == "11"
    assert parsed.raw_server_input == "S12"


def test_merge_effective_date_and_primary_opening_are_respected() -> None:
    assert load_server_mapping(as_of=date(2026, 9, 17))["26"] == "S26"
    assert load_server_mapping(as_of=date(2026, 9, 18))["26"] == "S25"
    assert load_server_mapping(as_of=date(2026, 7, 20))["34"] == "S34"
    assert load_server_mapping(as_of=date(2026, 7, 27))["34"] == "S36"


def test_runtime_mapping_file_matches_current_merge_rules() -> None:
    # The running Bot reads this file without a restart, so it must agree with
    # the fresh-process merge calculation for all currently open servers.
    static_mapping = json.loads(
        (BASE_DIR / "config" / "server_mapping.json").read_text(encoding="utf-8")
    )
    active_mapping = load_server_mapping(as_of=date(2026, 9, 21))

    assert {server_id: static_mapping[server_id] for server_id in active_mapping} == active_mapping


@pytest.mark.parametrize(
    ("day", "last_open_server"),
    [
        (date(2026, 9, 20), 51),
        (date(2026, 9, 21), 52),
        (date(2026, 9, 27), 52),
        (date(2026, 9, 28), 53),
        (date(2026, 10, 4), 53),
        (date(2026, 10, 5), 54),
        (date(2026, 10, 8), 55),
    ],
)
def test_planned_servers_activate_on_opening_day(day: date, last_open_server: int) -> None:
    active = load_server_mapping(as_of=day)

    assert max(map(int, active)) == last_open_server


def test_future_servers_are_registered_but_not_yet_active() -> None:
    planned = load_planned_server_dates(as_of=date(2026, 9, 20))

    assert planned == {
        "52": "2026-09-21",
        "53": "2026-09-28",
        "54": "2026-10-05",
        "55": "2026-10-08",
    }
    parsed = parse_member_application(
        "S52 Bubble",
        load_server_mapping(as_of=date(2026, 9, 20)),
        planned_server_dates=planned,
    )
    assert parsed.status == "需要人工审核"
    assert parsed.reason_code == "SERVER_NOT_OPEN_YET"
    assert parsed.server_name == "S52"


def test_open_and_planned_servers_together_require_manual_review() -> None:
    parsed = parse_member_application(
        "S51 S52 Bubble",
        load_server_mapping(as_of=date(2026, 9, 20)),
        planned_server_dates=load_planned_server_dates(as_of=date(2026, 9, 20)),
    )

    assert parsed.status == "需要人工审核"
    assert parsed.reason_code == "MULTIPLE_SERVER_IDS"


def test_planned_server_is_not_auto_rejected_with_another_invalid_number() -> None:
    parsed = parse_member_application(
        "S999 S52 Bubble",
        load_server_mapping(as_of=date(2026, 9, 20)),
        planned_server_dates=load_planned_server_dates(as_of=date(2026, 9, 20)),
    )

    assert parsed.status == "需要人工审核"
    assert parsed.reason_code == "SERVER_NOT_OPEN_YET"


@pytest.mark.parametrize("server_id", range(45, 52))
@pytest.mark.parametrize("prefix", ("", "S"))
def test_new_servers_are_recognized(server_id: int, prefix: str) -> None:
    parsed = parse_member_application(
        f"{prefix}{server_id} Bubble",
        load_server_mapping(as_of=date(2026, 9, 20)),
    )

    assert parsed.status == "可通过"
    assert parsed.server_id == str(server_id)
    assert parsed.server_name == f"S{server_id}"
    assert parsed.discord_nickname == f"S{server_id} Bubble"


def test_unconfigured_s56_is_not_accepted() -> None:
    parsed = parse_member_application(
        "S56 Bubble",
        load_server_mapping(as_of=date(2026, 10, 8)),
    )

    assert parsed.status == "区服ID异常"
    assert parsed.reason_code == "INVALID_SERVER_ID"


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


def test_member_review_service_approves_s51_join_request(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    adapter = FakeJoinRequestAdapter(raw_application="S51 Bubble")
    service = MemberReviewService(db_path, adapter=adapter)

    assert service.sync_discord_join_requests() == 1
    assert adapter.approved_requests == [("guild-1", "request-1", "1001", "S51 Bubble")]
    assert adapter.rejected_requests == []
    rows = MemberReviewRepository(db_path).list_filtered(processed_filter="已处理")
    assert rows[0]["server_id"] == "51"
    assert rows[0]["review_status"] == "已通过"


def test_member_review_service_approves_s12_join_request_as_s11(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    adapter = FakeJoinRequestAdapter(raw_application="S12 Bubble")
    service = MemberReviewService(db_path, adapter=adapter)

    assert service.sync_discord_join_requests() == 1
    assert adapter.approved_requests == [("guild-1", "request-1", "1001", "S11 Bubble")]
    assert adapter.rejected_requests == []
    row = MemberReviewRepository(db_path).list_filtered(processed_filter="已处理")[0]
    assert row["server_id"] == "11"
    assert row["server_name"] == "S11"
    assert row["raw_server_input"] == "S12"
    assert row["review_status"] == "已通过"


def test_running_service_activates_s52_without_restart_and_holds_early_request(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    current_day = {"value": date(2026, 9, 20)}
    monkeypatch.setattr(
        "app.member_review.service.current_server_date",
        lambda: current_day["value"],
    )
    adapter = FakeJoinRequestAdapter(raw_application="S52 Bubble")
    service = MemberReviewService(db_path, adapter=adapter)

    assert service.sync_discord_join_requests() == 1
    early_row = MemberReviewRepository(db_path).list_filtered()[0]
    assert early_row["review_status"] == "需要人工审核"
    assert early_row["reason_code"] == "SERVER_NOT_OPEN_YET"
    assert adapter.approved_requests == []
    assert adapter.rejected_requests == []

    current_day["value"] = date(2026, 9, 21)
    assert service.sync_discord_join_requests() == 1
    opened_row = MemberReviewRepository(db_path).get(int(early_row["id"]))
    assert opened_row["review_status"] == "已通过"
    assert adapter.approved_requests == [("guild-1", "request-1", "1001", "S52 Bubble")]


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
