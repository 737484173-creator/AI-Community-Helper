from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from app.vip.analytics.red_black_list import (
    DEFAULT_RED_BLACK_RULES,
    _trimmed_mean,
    build_red_black_board,
    filter_board_candidates,
)


AS_OF = datetime(2026, 9, 8)


def _player(
    role_id: int,
    *,
    server_type: str = "老服",
    user_source: str = "自然量",
    weekly: float = 100.0,
    previous: float | None = 100.0,
    rolling_average: float | None = 100.0,
    cumulative: float = 1000.0,
    login_days_ago: int = 1,
) -> dict[str, object]:
    return {
        "角色ID": str(role_id),
        "角色名": f"Player-{role_id}",
        "区服": "1" if server_type == "老服" else "22",
        "服务器类型": server_type,
        "用户来源": user_source,
        "累计充值": cumulative,
        "近一周充值": weekly,
        "前7日充值": previous,
        "过去28日周均充值": rolling_average,
        "最后登录时间": (pd.Timestamp(AS_OF) - pd.Timedelta(days=login_days_ago)).date(),
    }


def _rules(**overrides: object) -> dict[str, object]:
    rules = DEFAULT_RED_BLACK_RULES.copy()
    rules.update(overrides)
    return rules


def test_complete_red_count_is_not_truncated_to_top_15() -> None:
    rows = [
        _player(
            index,
            weekly=400 + index,
            previous=120,
            rolling_average=120,
            cumulative=2000 + index,
        )
        for index in range(1, 26)
    ]
    rows.extend(
        _player(index, weekly=20, cumulative=1000)
        for index in range(100, 125)
    )

    board = build_red_black_board(
        pd.DataFrame(rows),
        top_n=15,
        calculation_time=AS_OF,
        rules=_rules(red_group_percentile=0.50),
    )

    assert board["red_eligible_count"] == 25
    assert len(board["red_df"]) == 15
    assert board["eligible_count"] >= board["red_eligible_count"]


def test_small_four_way_group_falls_back_to_server_group() -> None:
    rows = [
        _player(index, user_source="自然量", weekly=100 + index)
        for index in range(1, 20)
    ]
    rows.extend(
        _player(index, user_source="CPS", weekly=200 + index)
        for index in range(100, 121)
    )

    board = build_red_black_board(pd.DataFrame(rows), calculation_time=AS_OF)
    natural = board["active_df"].query("用户来源 == '自然量'")
    cps = board["active_df"].query("用户来源 == 'CPS'")

    assert set(natural["基准范围"]) == {"老服大组"}
    assert set(natural["基准样本数"]) == {40}
    assert set(cps["基准范围"]) == {"老服 × CPS"}
    assert set(cps["基准样本数"]) == {21}


def test_trimmed_mean_removes_top_and_bottom_ten_percent() -> None:
    values = pd.Series([0.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10_000.0])

    assert _trimmed_mean(values, 0.10) == pytest.approx(10.0)


def test_display_filter_preserves_global_benchmark() -> None:
    rows = [
        _player(index, weekly=100 + index, cumulative=2000 + index)
        for index in range(1, 21)
    ]
    rows.append(
        _player(99, weekly=1000, previous=100, rolling_average=100, cumulative=9000)
    )
    board = build_red_black_board(pd.DataFrame(rows), calculation_time=AS_OF)
    global_row = board["red_candidates_df"].query("角色ID == '99'").iloc[0]
    visible = board["active_df"].query("角色ID == '99'")

    displayed = filter_board_candidates(board["red_candidates_df"], visible, top_n=15)

    assert len(displayed) == 1
    assert displayed.iloc[0]["分组稳健均值"] == global_row["分组稳健均值"]
    assert displayed.iloc[0]["基准样本数"] == global_row["基准样本数"]


@pytest.mark.parametrize(
    ("server_type", "weekly", "expected"),
    [("老服", 99.0, False), ("老服", 100.0, True), ("新服", 299.0, False), ("新服", 300.0, True)],
)
def test_red_list_respects_configurable_absolute_floor(
    server_type: str,
    weekly: float,
    expected: bool,
) -> None:
    rows = [
        _player(
            index,
            server_type=server_type,
            weekly=10,
            previous=10,
            rolling_average=10,
            cumulative=1500,
        )
        for index in range(1, 21)
    ]
    rows.append(
        _player(
            99,
            server_type=server_type,
            weekly=weekly,
            previous=20,
            rolling_average=20,
            cumulative=9000,
        )
    )
    board = build_red_black_board(pd.DataFrame(rows), calculation_time=AS_OF)

    assert ("99" in set(board["red_candidates_df"]["角色ID"].astype(str))) is expected


def test_zero_weekly_payment_is_a_signal_but_not_automatically_high_risk() -> None:
    rows = [
        _player(index, weekly=100, cumulative=1000 + index)
        for index in range(1, 21)
    ]
    rows.append(
        _player(
            99,
            weekly=0,
            previous=100,
            rolling_average=100,
            cumulative=9000,
            login_days_ago=1,
        )
    )
    board = build_red_black_board(pd.DataFrame(rows), calculation_time=AS_OF)
    player = board["black_candidates_df"].query("角色ID == '99'").iloc[0]

    assert player["风险指数"] < DEFAULT_RED_BLACK_RULES["risk_high_threshold"]
    assert player["风险等级"] == "观察"


def test_continuous_zero_payment_high_value_player_enters_black_list() -> None:
    rows = [
        _player(index, weekly=100, cumulative=1000 + index)
        for index in range(1, 21)
    ]
    rows.append(
        _player(
            99,
            weekly=0,
            previous=0,
            rolling_average=0,
            cumulative=9000,
            login_days_ago=28,
        )
    )

    board = build_red_black_board(pd.DataFrame(rows), calculation_time=AS_OF)
    player = board["black_candidates_df"].query("角色ID == '99'").iloc[0]

    assert player["基线类型"] == "连续零充值"
    assert bool(player["零充值信号"])
    assert player["风险等级"] == "高风险"
    assert "99" not in set(board["observation_df"]["角色ID"].astype(str))


def test_missing_history_is_observation_not_red_or_black() -> None:
    rows = [
        _player(index, weekly=100, cumulative=1500 + index)
        for index in range(1, 21)
    ]
    rows.append(
        _player(
            99,
            weekly=5000,
            previous=None,
            rolling_average=None,
            cumulative=9000,
        )
    )
    board = build_red_black_board(pd.DataFrame(rows), calculation_time=AS_OF)

    assert "99" in set(board["observation_df"]["角色ID"].astype(str))
    assert "99" not in set(board["red_candidates_df"]["角色ID"].astype(str))
    assert "99" not in set(board["black_candidates_df"]["角色ID"].astype(str))


def test_observation_list_has_black_list_compatible_risk_index_and_order() -> None:
    rows = [_player(index, weekly=100, cumulative=1000) for index in range(1, 21)]
    rows.extend(
        [
            _player(
                90,
                weekly=100,
                previous=100,
                rolling_average=100,
                cumulative=1000,
                login_days_ago=9,
            ),
            _player(
                91,
                weekly=0,
                previous=100,
                rolling_average=100,
                cumulative=1000,
                login_days_ago=1,
            ),
        ]
    )

    board = build_red_black_board(pd.DataFrame(rows), calculation_time=AS_OF)
    observation = board["observation_df"]

    assert {"风险指数", "风险等级", "运营建议"}.issubset(observation.columns)
    assert observation["风险指数"].is_monotonic_decreasing
    assert set(observation["角色ID"].astype(str)) == {"90", "91"}
    assert observation.iloc[0]["角色ID"] == "91"
