from __future__ import annotations

import gzip
from datetime import date

from app.game_monitor.ae_sync import (
    build_event_detail_definition,
    build_game_chat_rows,
    read_event_detail_artifact,
)


def test_event_detail_definition_filters_active_roles_and_real_speech() -> None:
    definition = build_event_detail_definition(
        ["role-1", "role-2"],
        range_start=date(2026, 9, 1),
        range_end=date(2026, 9, 7),
    )

    assert definition["event"] == "role_chat"
    assert definition["time_range"]["start_time"] == "2026-09-01 00:00:00"
    assert definition["filters"]["items"][0]["values"] == ["role-1", "role-2"]
    assert definition["filters"]["items"][1]["values"] == ["发言"]


def test_build_game_chat_rows_applies_shared_risk_rules_and_scope() -> None:
    raw_rows = [
        {
            "#event_time": "2026-09-07 10:00:00.000",
            "role_id": "role-1",
            "server_id": "22.0",
            "server_name": "S22",
            "chat_content": "THIS IS TRASH!!!",
            "chat_channel": "王国",
            "chat_type": "发言",
        },
        {
            "#event_time": "2026-09-07 11:00:00.000",
            "role_id": "role-1",
            "server_id": "1",
            "server_name": "S1",
            "chat_content": "NEWSHARE|payload",
            "chat_channel": "军团",
            "chat_type": "游戏分享",
        },
        {
            "#event_time": "2026-09-07 12:00:00.000",
            "role_id": "not-active",
            "server_id": "2",
            "server_name": "S2",
            "chat_content": "fuck this",
            "chat_channel": "王国",
            "chat_type": "发言",
        },
    ]

    rows = build_game_chat_rows(raw_rows, active_role_ids=["role-1"])

    assert len(rows) == 1
    assert rows[0]["server_id"] == "23"
    assert rows[0]["server_name"] == "S23"
    assert rows[0]["risk_level"] == "中风险"
    assert rows[0]["risk_type"] == "强烈负面"
    assert rows[0]["risk_reason"] == "强烈负面表达"


def test_new_s25_merge_is_applied_to_game_chat_sync() -> None:
    rows = build_game_chat_rows(
        [
            {
                "#event_time": "2026-09-18 10:00:00.000",
                "role_id": "role-1",
                "server_id": "27",
                "server_name": "S27",
                "chat_content": "hello",
                "chat_type": "发言",
            }
        ],
        active_role_ids=["role-1"],
    )

    assert [(row["server_id"], row["server_name"]) for row in rows] == [("25", "S25")]


def test_event_detail_artifact_accepts_ae_display_name_headers(tmp_path) -> None:
    artifact = tmp_path / "game-chat.csv.gz"
    payload = (
        '\ufeff\ufeff"Event time","角色ID","区服ID","区服名称",'
        '"聊天内容","聊天频道","聊天类型"\n'
        '"2026-09-09 01:01:10.000","role-1","1","S1",'
        '"hello","军团","发言"\n'
    )
    with gzip.open(artifact, "wb") as output:
        output.write(payload.encode("utf-8"))

    rows = read_event_detail_artifact(artifact)

    assert rows == [
        {
            "#event_time": "2026-09-09 01:01:10.000",
            "role_id": "role-1",
            "server_id": "1",
            "server_name": "S1",
            "chat_content": "hello",
            "chat_channel": "军团",
            "chat_type": "发言",
        }
    ]
