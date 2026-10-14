from datetime import datetime

import pandas as pd

from app.vip.profile import (
    build_profile_insight,
    cultivation_progress,
    giftbox_display_name,
    infer_package_price_tiers,
    normalize_purchase_rows,
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


def test_planned_server_open_dates_follow_holiday_schedule() -> None:
    expected = {
        "S50": "2026-09-14",
        "S51": "2026-09-17",
        "S52": "2026-09-21",
        "S53": "2026-09-28",
        "S54": "2026-10-05",
        "S55": "2026-10-08",
    }

    for server, open_date in expected.items():
        stage = server_stage(server, as_of=datetime(2026, 10, 8))
        assert stage.open_date.isoformat() == open_date
        assert stage.known is True


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


def test_missing_giftbox_name_uses_traceable_identifier() -> None:
    display_name, missing = giftbox_display_name("未命名礼包", "999999")

    assert display_name == "礼包 ID 999999"
    assert missing is True


def test_known_giftbox_name_is_preserved() -> None:
    display_name, missing = giftbox_display_name("城建补给", "gift-1::城建补给")

    assert display_name == "城建补给"
    assert missing is False


def test_dragon_coin_label_is_localized() -> None:
    display_name, missing = giftbox_display_name("Dragon Coin*648", "931707")

    assert display_name == "龙币 × 648"
    assert missing is False


def test_verified_dragon_coin_tier_resolves_cached_unnamed_row() -> None:
    display_name, missing = giftbox_display_name("未命名礼包", "931707")

    assert display_name == "龙币 × 1296"
    assert missing is False


def test_verified_package_name_resolves_cached_unnamed_row() -> None:
    display_name, missing = giftbox_display_name("未命名礼包", "2000005")

    assert display_name == "装备升星礼包"
    assert missing is False


def test_verified_activity_name_resolves_cached_unnamed_row() -> None:
    display_name, missing = giftbox_display_name("未命名礼包", "283005")

    assert display_name == "机甲锻造豪礼"
    assert missing is False


def test_ambiguous_activity_id_stays_traceable_until_resync() -> None:
    display_name, missing = giftbox_display_name("未命名礼包", "52")

    assert display_name == "礼包 ID 52"
    assert missing is True


def test_cached_dragon_coin_funding_is_not_demand_evidence() -> None:
    normalized = normalize_purchase_rows(
        pd.DataFrame(
            [
                {
                    "giftbox_id": "931707",
                    "giftbox_name": "未命名礼包",
                    "payment_channel": "cash",
                    "category": "其他",
                    "is_demand_evidence": 1,
                }
            ]
        )
    )

    assert normalized.iloc[0]["giftbox_name"] == "龙币 × 1296"
    assert normalized.iloc[0]["category"] == "龙币充值"
    assert bool(normalized.iloc[0]["is_demand_evidence"]) is False


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


def test_profile_combines_payment_methods_by_package_price_tier() -> None:
    player = pd.Series(
        {
            "角色ID": "100",
            "区服": "S23",
            "服务器类型": "新服",
            "累计充值": 3000.0,
            "近一周充值": 100.0,
            "前7日充值": 80.0,
            "build_fp": 10.0,
            "tech_fp": 10.0,
            "soldier_fp": 10.0,
            "beast_fp": 10.0,
            "hero_fp": 10.0,
            "hiryu_fp": 10.0,
            "com_fp": 10.0,
            "leg_tech_fp": 10.0,
            "cur_fp": 80.0,
        }
    )
    peers = pd.DataFrame([{**player.to_dict(), "角色ID": str(index)} for index in range(6)])
    purchases = pd.DataFrame(
        [
            {
                "window_key": "lifetime",
                "category": "建筑发展",
                "giftbox_name": "现金建筑礼包",
                "purchase_count": 2,
                "payment_amount": 20.0,
                "payment_channel": "cash",
                "is_demand_evidence": 1,
                "items_json": "[]",
            },
            {
                "window_key": "lifetime",
                "category": "科研发展",
                "giftbox_name": "龙币科研礼",
                "purchase_count": 3,
                "payment_amount": 328.0,
                "payment_channel": "dragon_coin",
                "is_demand_evidence": 1,
                "items_json": "[]",
            },
            {
                "window_key": "recent_30d",
                "category": "科研发展",
                "giftbox_name": "龙币科研礼",
                "purchase_count": 1,
                "payment_amount": 128.0,
                "payment_channel": "dragon_coin",
                "is_demand_evidence": 1,
                "items_json": "[]",
            },
        ]
    )

    insight = build_profile_insight(
        player,
        purchases,
        peers,
        as_of=datetime(2026, 9, 17),
        price_tiers={
            "name:现金建筑礼包": 9.99,
            "name:龙币科研礼": 19.99,
        },
    )

    assert insight.coverage.dragon_coin_purchases is True
    assert insight.primary is not None
    assert insight.primary.category == "科研发展"
    assert insight.primary.recent_amount == 19.99
    assert insight.primary.recent_cash_amount == 0
    assert insight.primary.recent_dragon_coin_amount == 128


def test_package_tier_uses_vip_cohort_modal_nominal_price() -> None:
    rows = pd.DataFrame(
        [
            {
                "giftbox_id": "gift-1::城建补给",
                "giftbox_name": "城建补给",
                "window_key": "lifetime",
                "payment_channel": "cash",
                "is_demand_evidence": 1,
                "purchase_count": 2,
                "payment_amount": 39.98,
            },
            {
                "giftbox_id": "gift-1::城建补给",
                "giftbox_name": "城建补给",
                "window_key": "lifetime",
                "payment_channel": "cash",
                "is_demand_evidence": 1,
                "purchase_count": 3,
                "payment_amount": 59.97,
            },
            {
                "giftbox_id": "gift-1::城建补给",
                "giftbox_name": "城建补给",
                "window_key": "lifetime",
                "payment_channel": "cash",
                "is_demand_evidence": 1,
                "purchase_count": 1,
                "payment_amount": 26.72,
            },
        ]
    )

    tiers = infer_package_price_tiers(rows)
    normalized = normalize_purchase_rows(rows.tail(1), price_tiers=tiers)

    assert tiers["id-name:gift-1|城建补给"] == 19.99
    assert normalized.iloc[0]["price_tier"] == 19.99
    assert normalized.iloc[0]["tier_spend"] == 19.99


def test_cached_category_is_recomputed_from_package_name_not_secondary_items() -> None:
    normalized = normalize_purchase_rows(
        pd.DataFrame(
            [
                {
                    "giftbox_id": "91012::超值豪礼",
                    "giftbox_name": "超值豪礼",
                    "window_key": "lifetime",
                    "payment_channel": "cash",
                    "category": "士兵养成",
                    "purchase_count": 1,
                    "payment_amount": 4.99,
                    "items_json": '[{"item_name":"士兵训练加速"}]',
                }
            ]
        )
    )

    assert normalized.iloc[0]["category"] == "其他"
