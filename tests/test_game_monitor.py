from __future__ import annotations

from datetime import date

import pandas as pd

from app.dashboard.views.game_monitor import (
    _ranking_chart,
    _risk_trend_chart,
    _trend_chart,
    daily_message_trend,
    daily_risk_trend,
    period_change,
    resolve_date_range,
    sort_risk_messages,
)
from app.dashboard.views.game_monitor_risk import (
    player_ranking_html,
    player_risk_ranking,
    risk_excel_bytes,
    risk_export_frame,
    server_risk_chart,
    server_risk_distribution,
)


def test_resolve_date_range_includes_today() -> None:
    today = date(2026, 9, 9)

    assert resolve_date_range("今日", today) == (today, today)
    assert resolve_date_range("近7日", today) == (date(2026, 9, 3), today)
    assert resolve_date_range("近30日", today) == (date(2026, 8, 11), today)


def test_daily_trend_marks_a_large_peak_after_a_stable_baseline() -> None:
    dates = [pd.Timestamp("2026-09-01") + pd.Timedelta(days=index) for index in range(8)]
    rows: list[dict[str, object]] = []
    for day_index, event_date in enumerate(dates):
        count = 30 if day_index == 7 else 5
        rows.extend({"event_time": event_date} for _ in range(count))
    dataframe = pd.DataFrame(rows)

    trend = daily_message_trend(dataframe, date(2026, 9, 1), date(2026, 9, 8))

    assert bool(trend.iloc[-1]["异常峰值"]) is True
    assert period_change(trend)[1].startswith("较前期上升")


def test_high_risk_priority_sorts_level_then_latest() -> None:
    dataframe = pd.DataFrame(
        [
            {"risk_level": "低风险", "event_time": pd.Timestamp("2026-09-09 12:00")},
            {"risk_level": "高风险", "event_time": pd.Timestamp("2026-09-08 12:00")},
            {"risk_level": "高风险", "event_time": pd.Timestamp("2026-09-09 11:00")},
        ]
    )

    result = sort_risk_messages(dataframe, "高风险优先")

    assert result["risk_level"].tolist() == ["高风险", "高风险", "低风险"]
    assert result.iloc[0]["event_time"] == pd.Timestamp("2026-09-09 11:00")


def test_daily_risk_trend_keeps_zero_days_and_level_breakdown() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "event_time": pd.Timestamp("2026-09-01 10:00"),
                "risk_level": "高风险",
            },
            {
                "event_time": pd.Timestamp("2026-09-01 11:00"),
                "risk_level": "中风险",
            },
            {
                "event_time": pd.Timestamp("2026-09-03 12:00"),
                "risk_level": "低风险",
            },
        ]
    )

    daily = daily_risk_trend(dataframe, date(2026, 9, 1), date(2026, 9, 3))

    assert daily["风险总量"].tolist() == [2, 0, 1]
    assert daily["高风险"].tolist() == [1, 0, 0]
    assert daily.loc[0, "高风险明细"] == "1 条 · 50%"
    assert daily.loc[1, "低风险明细"] == "0 条 · 0%"


def test_game_risk_trend_chart_matches_chat_monitor_layered_style() -> None:
    daily = daily_risk_trend(
        pd.DataFrame(
            [
                {
                    "event_time": pd.Timestamp("2026-09-01 10:00"),
                    "risk_level": "高风险",
                },
                {
                    "event_time": pd.Timestamp("2026-09-02 11:00"),
                    "risk_level": "低风险",
                },
            ]
        ),
        date(2026, 9, 1),
        date(2026, 9, 3),
    )

    spec = _risk_trend_chart(daily, date(2026, 9, 1), date(2026, 9, 3)).to_dict()
    marks = [
        layer.get("mark", {}).get("type")
        if isinstance(layer.get("mark"), dict)
        else layer.get("mark")
        for layer in spec["layer"]
    ]

    assert "vconcat" not in spec
    assert spec["height"] == 320
    assert "line" in marks
    assert "bar" in marks


def test_message_trend_chart_has_nearest_point_hover_feedback() -> None:
    daily = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "消息数": [3, 7],
            "基线": [3.0, 5.0],
            "异常峰值": [False, False],
        }
    )
    dataframe = pd.DataFrame(
        {
            "event_time": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "server_id": ["1", "1"],
            "server_name": ["S1", "S1"],
        }
    )

    spec = _trend_chart(
        dataframe,
        daily,
        date(2026, 9, 1),
        date(2026, 9, 2),
        (),
    ).to_dict()

    assert spec["params"][0]["name"] == "game_message_date_hover"
    assert any(layer.get("encoding", {}).get("size") for layer in spec["layer"])
    assert any(layer.get("mark", {}).get("type") == "rule" for layer in spec["layer"])


def test_server_ranking_chart_highlights_hovered_bar() -> None:
    spec = _ranking_chart(
        pd.DataFrame({"区服": ["S1", "S2"], "消息数": [12, 7]})
    ).to_dict()

    assert spec["params"][0]["name"] == "game_server_bar_hover"
    assert "condition" in spec["encoding"]["color"]
    assert "condition" in spec["encoding"]["opacity"]


def test_risk_server_distribution_keeps_level_breakdown_and_order() -> None:
    dataframe = pd.DataFrame(
        [
            {"server_id": "6", "server_name": "S6", "risk_level": "高风险"},
            {"server_id": "6", "server_name": "S6", "risk_level": "中风险"},
            {"server_id": "14", "server_name": "S14", "risk_level": "高风险"},
            {"server_id": "6", "server_name": "S6", "risk_level": "高风险"},
        ]
    )

    result = server_risk_distribution(dataframe)

    assert result["区服"].astype(str).drop_duplicates().tolist() == ["S6", "S14"]
    assert int(result[result["区服"].astype(str).eq("S6")]["风险消息"].sum()) == 3
    assert set(result["风险等级"]) == {"高风险", "中风险"}


def test_risk_server_chart_has_hover_feedback() -> None:
    distribution = pd.DataFrame(
        {
            "区服": ["S6", "S6", "S14"],
            "风险等级": ["高风险", "中风险", "高风险"],
            "风险消息": [4, 2, 3],
            "区服总量": [6, 6, 3],
        }
    )

    spec = server_risk_chart(distribution).to_dict()

    assert spec["params"][0]["name"] == "game_risk_server_hover"
    assert "condition" in spec["encoding"]["opacity"]
    assert "condition" in spec["encoding"]["stroke"]


def test_player_risk_ranking_enriches_actual_vip_profile() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "role_id": "1001",
                "server_id": "6",
                "server_name": "S6",
                "event_time": pd.Timestamp("2026-09-09 10:00"),
                "risk_level": "高风险",
                "risk_type": "脏字/攻击",
                "chat_content": "sample one",
            },
            {
                "role_id": "1001",
                "server_id": "6",
                "server_name": "S6",
                "event_time": pd.Timestamp("2026-09-08 10:00"),
                "risk_level": "中风险",
                "risk_type": "脏字/攻击",
                "chat_content": "sample two",
            },
            {
                "role_id": "1002",
                "server_id": "14",
                "server_name": "S14",
                "event_time": pd.Timestamp("2026-09-09 09:00"),
                "risk_level": "高风险",
                "risk_type": "脏字/攻击",
                "chat_content": "sample three",
            },
        ]
    )
    profiles = [
        {
            "role_id": "1001",
            "role_name": "Actual Player",
            "last_login_time": "2026-09-09 08:00:00",
            "total_payment_amount": 125.5,
            "payment_7d_amount": 12.0,
            "server_type": "老服",
            "user_source": "自然量",
        }
    ]

    result = player_risk_ranking(dataframe, profiles)
    html = player_ranking_html(result, dataframe, "脏话数量最多的玩家")

    assert result.iloc[0]["role_id"] == "1001"
    assert result.iloc[0]["角色名"] == "Actual Player"
    assert int(result.iloc[0]["风险消息"]) == 2
    assert int(result.iloc[0]["活跃天数"]) == 2
    assert "<details" in html
    assert "点击查看" in html
    assert "sample one" in html


def test_risk_export_is_excel_only_detail_source() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "role_id": "1001",
                "server_id": "6",
                "server_name": "S6",
                "event_time": pd.Timestamp("2026-09-09 10:00"),
                "risk_level": "高风险",
                "risk_type": "脏字/攻击",
                "chat_content": "raw message",
                "risk_reason": "matched rule",
            }
        ]
    )
    export = risk_export_frame(dataframe, [{"role_id": "1001", "role_name": "Player"}])
    payload = risk_excel_bytes(export)

    assert export.loc[0, "角色名"] == "Player"
    assert export.loc[0, "消息原文"] == "raw message"
    assert payload.startswith(b"PK")
