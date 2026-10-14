from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.vip.analytics.red_black_list import build_red_black_board
from app.vip.scoring.router import classify_player, score_dataframe
from app.vip.service import (
    CONTACT_PRIORITIES,
    build_vip_workbook,
    contact_count_for_group,
    group_metrics,
    is_retired_player,
    mark_retired_players,
    server_contact_counts,
    vip_summary_metrics,
    VIPWorkbook,
)
from app.vip.profile import server_stage
from app.vip.server_merges import apply_server_merges, canonical_server_id, server_merge_summary
from app.vip.utils.excel_reader import (
    ExcelReadReport,
    _infer_server_type,
    _infer_user_source,
    detect_vip_columns,
)


AS_OF = datetime(2026, 7, 5)


def _vip_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "角色ID": "1",
                "区服": "6",
                "角色名": "OldVip",
                "最后登录时间": "2026-06-01",
                "累计充值": 21000,
                "近一周充值": 0,
                "服务器类型": "老服",
                "用户来源": "自然量",
            },
            {
                "角色ID": "2",
                "区服": "22",
                "角色名": "NewOrganic",
                "最后登录时间": "2026-06-20",
                "累计充值": 1000,
                "近一周充值": 1000,
                "服务器类型": "新服",
                "用户来源": "自然量",
            },
            {
                "角色ID": "3",
                "区服": "22",
                "角色名": "CpsVip",
                "最后登录时间": "2026-07-05",
                "累计充值": 15000,
                "近一周充值": 3000,
                "服务器类型": "新服",
                "用户来源": "CPS",
            },
            {
                "角色ID": "4",
                "区服": "/",
                "角色名": "Retired",
                "最后登录时间": "2026-07-05",
                "累计充值": 99999,
                "近一周充值": 99999,
                "服务器类型": "老服",
                "用户来源": "自然量",
            },
        ]
    )


def test_excel_reader_infers_source_metadata() -> None:
    assert _infer_server_type("1") == "老服"
    assert _infer_server_type("S2") == "老服"
    assert _infer_server_type(20) == "老服"
    assert _infer_server_type("11") == "老服"
    assert _infer_server_type("21") == "老服"
    assert _infer_server_type("S21") == "老服"
    assert _infer_server_type("S22") == "新服"
    assert _infer_server_type(pd.NA) == ""
    assert _infer_user_source("Sheet2") == "自然量"
    assert _infer_user_source("Sheet3") == "CPS"
    assert _infer_user_source("Sheet1") == ""


def test_excel_reader_only_uses_explicit_7_and_14_day_payment_columns() -> None:
    current_only = detect_vip_columns(pd.DataFrame(columns=["角色ID", "近一周充值"]))
    complete = detect_vip_columns(
        pd.DataFrame(columns=["角色ID", "近一周充值", "前7日充值", "过去28日周均充值"])
    )

    assert current_only["前7日充值"] is None
    assert current_only["过去28日周均充值"] is None
    assert complete["前7日充值"] == "前7日充值"
    assert complete["过去28日周均充值"] == "过去28日周均充值"


def test_server_merge_groups_resolve_to_current_primary_server() -> None:
    expected = {
        "1": "1",
        "4": "1",
        "5": "1",
        "8": "1",
        "9": "1",
        "2": "6",
        "3": "6",
        "6": "6",
        "7": "6",
        "10": "6",
        "11": "11",
        "12": "11",
        "13": "11",
        "14": "14",
        "15": "14",
        "16": "14",
        "17": "19",
        "19": "19",
        "21": "19",
        "18": "20",
        "20": "20",
        "22": "23",
        "23": "23",
        "24": "23",
        "25": "25",
        "26": "25",
        "27": "25",
        "28": "28",
        "29": "28",
        "30": "28",
        "31": "31",
        "32": "31",
        "33": "31",
        "34": "36",
        "35": "36",
        "36": "36",
    }

    for source, primary in expected.items():
        assert canonical_server_id(f"S{source}") == primary


def test_s25_merge_retains_source_and_effective_date() -> None:
    merged = apply_server_merges(pd.DataFrame({"区服": ["S25", "S26", "S27"]}))

    assert merged["区服"].tolist() == ["25", "25", "25"]
    assert merged["原区服"].tolist() == ["25", "26", "27"]
    assert "S25（S25 / S26 / S27；2026-09-18 生效）" in server_merge_summary()
    assert server_stage("S26", as_of=datetime(2026, 9, 20)).server_id == "25"


def test_workbook_canonicalizes_merged_servers_before_scoring() -> None:
    players = _vip_rows().iloc[:3].copy()
    players.loc[players.index[0], ["区服", "服务器类型"]] = ["S4", "老服"]
    players.loc[players.index[1], ["区服", "服务器类型"]] = ["S21", "新服"]
    players.loc[players.index[2], ["区服", "服务器类型"]] = ["S22", "新服"]
    workbook = build_vip_workbook(
        players,
        ExcelReadReport(sheet_names=["test"], matched_columns={}, missing_fields=[]),
        as_of=AS_OF,
    )

    by_id = workbook.scored_df.set_index("角色ID")
    assert by_id.loc["1", "原区服"] == "4"
    assert by_id.loc["1", "区服"] == "1"
    assert by_id.loc["2", "区服"] == "19"
    assert by_id.loc["2", "服务器类型"] == "老服"
    assert by_id.loc["3", "区服"] == "23"
    assert by_id.loc["3", "服务器类型"] == "新服"


def test_scoring_router_classifies_vip_groups() -> None:
    scored = score_dataframe(_vip_rows().iloc[:3], as_of=AS_OF)

    assert scored.iloc[0]["玩家分组"] == "老服自然量"
    assert scored.iloc[1]["玩家分组"] == "新服自然量"
    assert scored.iloc[2]["玩家分组"] == "新服CPS"
    assert classify_player(pd.Series({"服务器类型": "老服", "用户来源": "CPS"})) == "老服CPS"


def test_scoring_router_scores_old_server_cps_as_independent_group() -> None:
    old_cps = _vip_rows().iloc[[0]].copy()
    old_cps.loc[:, "用户来源"] = "CPS"

    scored = score_dataframe(old_cps, as_of=AS_OF)

    assert scored.iloc[0]["玩家分组"] == "老服CPS"
    assert scored.iloc[0]["触达优先级"] != "数据异常：无法识别服务器类型或用户来源"


def test_retired_when_last_login_reaches_30_days_from_snapshot_day() -> None:
    players = pd.DataFrame(
        [
            {**_vip_rows().iloc[1].to_dict(), "角色ID": "29", "最后登录时间": "2026-06-06"},
            {**_vip_rows().iloc[1].to_dict(), "角色ID": "30", "最后登录时间": "2026-06-05"},
        ]
    )

    scored = mark_retired_players(score_dataframe(players, as_of=AS_OF), as_of=AS_OF)
    retired = is_retired_player(scored, as_of=AS_OF)

    assert not bool(retired.iloc[0])
    assert bool(retired.iloc[1])
    assert scored.iloc[1]["玩家分组"] == "已退游"
    assert "达到 30 天" in scored.iloc[1]["原因"]


def test_login_risk_uses_7_day_observation_and_14_day_high_risk_windows() -> None:
    base = {
        **_vip_rows().iloc[0].to_dict(),
        "累计充值": 5000,
        "近一周充值": 100,
        "前7日充值": 100,
    }
    players = pd.DataFrame(
        [
            {**base, "角色ID": "6", "最后登录时间": "2026-06-29"},
            {**base, "角色ID": "7", "最后登录时间": "2026-06-28"},
            {**base, "角色ID": "14", "最后登录时间": "2026-06-21"},
        ]
    )

    scored = score_dataframe(players, as_of=AS_OF)

    assert scored["风险分"].tolist() == [0, 15, 40]
    assert scored["触达优先级"].tolist() == ["观察跟进", "观察跟进", "立即触达"]
    assert "7 天以上未登录" in scored.iloc[1]["原因"]
    assert "14 天以上未登录" in scored.iloc[2]["原因"]


def test_payment_risk_uses_adjacent_7_day_windows() -> None:
    base = {
        **_vip_rows().iloc[0].to_dict(),
        "累计充值": 1000,
        "最后登录时间": "2026-07-04",
    }
    players = pd.DataFrame(
        [
            {**base, "角色ID": "stable", "近一周充值": 100, "前7日充值": 100},
            {**base, "角色ID": "7d", "近一周充值": 0, "前7日充值": 100},
            {**base, "角色ID": "14d", "近一周充值": 0, "前7日充值": 0},
        ]
    )

    scored = score_dataframe(players, as_of=AS_OF)

    assert scored["风险分"].tolist() == [0, 20, 35]
    assert scored["触达优先级"].tolist() == ["暂不触达", "观察跟进", "优先触达"]
    assert "近 7 日未充值" in scored.iloc[1]["原因"]
    assert "连续 14 日未充值" in scored.iloc[2]["原因"]


def test_vip_service_filters_retired_players_from_contact_metrics() -> None:
    scored = mark_retired_players(score_dataframe(_vip_rows(), as_of=AS_OF), as_of=AS_OF)
    active = scored[scored["区服"].astype(str) != "/"].copy()
    workbook = VIPWorkbook(
        raw_df=_vip_rows(),
        scored_df=scored,
        active_df=active,
        report=object(),
        retired_count=1,
        abnormal_count=0,
        missing_page_columns=[],
    )

    metrics = vip_summary_metrics(workbook)

    assert metrics["总玩家"] == 4
    assert metrics["有效玩家"] == 3
    assert metrics["退游玩家"] == 1
    assert metrics["待触达"] == int(active["触达优先级"].isin(CONTACT_PRIORITIES).sum())
    assert contact_count_for_group(active, "新服CPS") == 1
    assert "退游玩家" not in set(group_metrics(active)["玩家分组"])
    assert server_contact_counts(active).iloc[0]["待触达人数"] >= 1


def test_red_black_board_excludes_retired_players() -> None:
    board = build_red_black_board(_vip_rows(), top_n=15, calculation_time=AS_OF)
    red_ids = set(board["red_df"]["角色ID"].astype(str))
    black_ids = set(board["black_df"]["角色ID"].astype(str))

    assert "4" not in red_ids
    assert "4" not in black_ids
    assert red_ids.isdisjoint(black_ids)
