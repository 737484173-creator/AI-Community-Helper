from datetime import datetime

import pandas as pd

from app.vip.profile import (
    build_profile_insight,
    cultivation_progress,
    payment_direction,
    profile_coverage,
    recommendation_state,
    server_stage,
)


def test_early_servers_are_fully_unlocked_after_merge() -> None:
    stage = server_stage("S4", as_of=datetime(2026, 9, 17))

    assert stage.server_id == "1"
    assert stage.label == "S1"
    assert stage.fully_unlocked is True
    assert stage.age_days is None


def test_s11_plus_uses_primary_server_open_date_and_new_days() -> None:
    stage = server_stage("S24", as_of=datetime(2026, 9, 17))

    assert stage.server_id == "23"
    assert stage.open_date.isoformat() == "2026-05-26"
    assert stage.age_days == 115
    assert stage.fully_unlocked is False


def test_cultivation_progress_separates_open_and_upcoming_paths() -> None:
    unlocked, upcoming, conditional = cultivation_progress(
        "S49",
        as_of=datetime(2026, 9, 17),
    )

    assert {item["name"] for item in unlocked} >= {
        "城建",
        "科研",
        "士兵",
        "巨兽",
    }
    assert upcoming[0]["name"] == "飞龙升星/升级"
    assert upcoming[0]["days_remaining"] == 13
    assert {item["name"] for item in conditional} >= {"龙鳞升星", "超导改造", "徽章改造"}


def test_profile_with_only_recharge_data_withholds_demand_recommendation() -> None:
    player = pd.Series(
        {
            "累计充值": 2000.0,
            "近一周充值": 100.0,
            "前7日充值": 50.0,
        }
    )

    coverage = profile_coverage(player)
    title, _, tone = recommendation_state(coverage)

    assert coverage.available_count == 1
    assert title == "画像证据待同步"
    assert tone == "pending"


def test_payment_direction_uses_current_and_previous_seven_day_windows() -> None:
    player = pd.Series({"近一周充值": 120.0, "前7日充值": 80.0})

    label, note = payment_direction(player)

    assert label == "付费升温"
    assert "50%" in note


def test_profile_insight_combines_purchase_preference_and_power_gap() -> None:
    player = pd.Series(
        {
            "角色ID": "100",
            "区服": "S23",
            "服务器类型": "新服",
            "累计充值": 3000.0,
            "近一周充值": 100.0,
            "前7日充值": 80.0,
            "build_fp": 5.0,
            "tech_fp": 25.0,
            "soldier_fp": 20.0,
            "beast_fp": 20.0,
            "hero_fp": 10.0,
            "hiryu_fp": 10.0,
            "com_fp": 5.0,
            "leg_tech_fp": 5.0,
            "cur_fp": 100.0,
        }
    )
    peers = pd.DataFrame(
        [
            {
                **player.to_dict(),
                "角色ID": str(index),
                "build_fp": 20.0,
                "tech_fp": 15.0,
            }
            for index in range(6)
        ]
    )
    purchases = pd.DataFrame(
        [
            {
                "window_key": "lifetime",
                "category": "建筑发展",
                "giftbox_name": "城建补给",
                "purchase_count": 10,
                "payment_amount": 200.0,
                "items_json": '[]',
            },
            {
                "window_key": "recent_30d",
                "category": "建筑发展",
                "giftbox_name": "城建补给",
                "purchase_count": 3,
                "payment_amount": 60.0,
                "items_json": '[]',
            },
            {
                "window_key": "lifetime",
                "category": "通用资源",
                "giftbox_name": "资源补给",
                "purchase_count": 2,
                "payment_amount": 20.0,
                "items_json": '[]',
            },
        ]
    )

    insight = build_profile_insight(
        player,
        purchases,
        peers,
        as_of=datetime(2026, 9, 17),
    )

    assert insight.coverage.available_count == 3
    assert insight.primary is not None
    assert insight.primary.category == "建筑发展"
    assert insight.primary.gap_ratio > 0.5
