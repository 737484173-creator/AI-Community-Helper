from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from app.vip.scoring.router import load_scoring_rules
from app.vip.server_merges import apply_server_merges
from app.vip.service import is_retired_player
from app.vip.utils.excel_reader import _infer_server_type


DEFAULT_RED_BLACK_RULES: dict[str, Any] = {
    "minimum_group_size": 20,
    "trim_ratio": 0.10,
    "red_group_multiplier": 1.50,
    "red_personal_growth_ratio": 0.30,
    "red_group_percentile": 0.80,
    "red_minimum_payment": {"老服": 100.0, "新服": 300.0},
    "high_value_percentile": 0.80,
    "high_value_minimum": {"老服": 5000.0, "新服": 1000.0},
    "black_personal_decline_ratio": 0.30,
    "black_zero_payment_signal_score": 25.0,
    "login_risk_start_days": 7,
    "login_high_risk_days": 14,
    "login_observe_score": 15.0,
    "login_high_risk_score": 30.0,
    "payment_zero_7d_score": 25.0,
    "payment_zero_14d_score": 50.0,
    "risk_high_threshold": 70.0,
    "risk_medium_threshold": 45.0,
    "top_n": 15,
}


def load_red_black_rules() -> dict[str, Any]:
    configured = load_scoring_rules().get("red_black", {})
    rules = DEFAULT_RED_BLACK_RULES.copy()
    if isinstance(configured, dict):
        rules.update(configured)
    return rules


RED_BLACK_RULES = load_red_black_rules()


def build_red_black_board(
    df: pd.DataFrame,
    *,
    top_n: int | None = None,
    calculation_time: datetime | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build global benchmarks, complete eligible sets, and Top-N display sets."""
    effective_time = calculation_time or datetime.now()
    active_rules = (rules or load_red_black_rules()).copy()
    display_limit = int(top_n or active_rules["top_n"])
    active_df = _prepare_active_dataframe(df, as_of=effective_time)
    enriched_df, benchmark_df = _append_benchmark_columns(active_df, active_rules)
    red_candidates = _build_red_candidates(enriched_df, active_rules)
    black_candidates = _build_black_candidates(enriched_df, red_candidates, active_rules)
    observation_df = _build_observation_list(
        enriched_df,
        red_candidates,
        black_candidates,
        active_rules,
    )

    return {
        "active_df": enriched_df,
        "red_candidates_df": red_candidates,
        "black_candidates_df": black_candidates,
        "observation_df": observation_df,
        "red_df": _top_display(red_candidates, display_limit),
        "black_df": _top_display(black_candidates, display_limit),
        "benchmark_df": benchmark_df,
        "eligible_count": len(red_candidates) + len(black_candidates),
        "red_eligible_count": len(red_candidates),
        "black_eligible_count": len(black_candidates),
        "observation_count": len(observation_df),
        "calculation_time": effective_time,
        "rules": active_rules,
    }


def filter_board_candidates(
    candidates: pd.DataFrame,
    visible_players: pd.DataFrame,
    *,
    top_n: int,
) -> pd.DataFrame:
    """Filter only the display set without recomputing global benchmark columns."""
    if candidates.empty or visible_players.empty:
        return candidates.head(0).copy()
    visible_keys = set(visible_players["_玩家键"].astype(str))
    filtered = candidates[candidates["_玩家键"].astype(str).isin(visible_keys)].copy()
    return _top_display(filtered, top_n)


def _prepare_active_dataframe(df: pd.DataFrame, *, as_of: datetime) -> pd.DataFrame:
    required_columns = [
        "角色ID",
        "角色名",
        "区服",
        "服务器类型",
        "用户来源",
        "累计充值",
        "近一周充值",
        "前7日充值",
        "过去28日周均充值",
        "最后登录时间",
    ]
    output = df.copy()
    for column in required_columns:
        if column not in output.columns:
            output[column] = pd.NA

    output = apply_server_merges(output)
    inferred_server_type = output["区服"].map(_infer_server_type)
    output["服务器类型"] = inferred_server_type.where(
        inferred_server_type.ne(""), output["服务器类型"]
    )

    for column in ("区服", "角色名", "服务器类型", "用户来源"):
        output[column] = output[column].astype("string").str.strip()
    output["用户来源"] = output["用户来源"].replace(
        {"NATURAL": "自然量", "Natural": "自然量", "natural": "自然量"}
    )
    zone_text = output["区服"].fillna("").astype(str).str.strip()
    role_text = output["角色名"].fillna("").astype(str).str.strip()
    valid_role_name = ~role_text.str.lower().isin({"", "/", "nan", "<na>", "none", "未命名"})
    output = output[
        zone_text.ne("/")
        & valid_role_name
        & ~is_retired_player(output, as_of=as_of)
    ].copy()

    output["累计充值"] = pd.to_numeric(output["累计充值"], errors="coerce").fillna(0.0)
    output["近一周充值"] = pd.to_numeric(output["近一周充值"], errors="coerce").fillna(0.0)
    output["前7日充值"] = pd.to_numeric(output["前7日充值"], errors="coerce")
    output["过去28日周均充值"] = pd.to_numeric(
        output["过去28日周均充值"], errors="coerce"
    )
    output["最后登录时间"] = pd.to_datetime(output["最后登录时间"], errors="coerce")
    output = output[
        output["服务器类型"].isin(["老服", "新服"])
        & output["用户来源"].isin(["自然量", "CPS"])
    ].copy()
    reference_day = pd.Timestamp(as_of).tz_localize(None).normalize()
    output["最后登录间隔"] = (
        reference_day - output["最后登录时间"].dt.tz_localize(None).dt.normalize()
    ).dt.days.clip(lower=0).fillna(0).astype(int)
    missing_history = (
        output["过去28日周均充值"].isna() | output["前7日充值"].isna()
    )
    zero_baseline = ~missing_history & output["过去28日周均充值"].le(0)
    zero_payment = output["近一周充值"].le(0)
    output["趋势状态"] = "可比较"
    output["基线类型"] = "历史基线"
    output.loc[missing_history, ["趋势状态", "基线类型"]] = ["观察期", "数据缺失"]
    output.loc[zero_baseline & zero_payment, "基线类型"] = "连续零充值"
    output.loc[
        zero_baseline & ~zero_payment, ["趋势状态", "基线类型"]
    ] = ["观察期", "新增充值无历史基线"]
    output["零充值信号"] = zero_payment
    output["_玩家键"] = (
        output["角色ID"].astype(str).str.strip()
        + "|"
        + output["区服"].astype(str).str.strip()
    )
    return output.reset_index(drop=True)


def _append_benchmark_columns(
    df: pd.DataFrame,
    rules: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df.copy(), pd.DataFrame()

    output = df.copy()
    minimum_group_size = int(rules["minimum_group_size"])
    group_counts = output.groupby(["服务器类型", "用户来源"])["角色ID"].transform("size")
    output["原始分组"] = output["服务器类型"] + " × " + output["用户来源"]
    output["基准层级"] = group_counts.map(
        lambda count: "服务器类型 × 用户来源" if int(count) >= minimum_group_size else "服务器类型回退"
    )
    output["基准范围"] = output.apply(
        lambda row: row["原始分组"]
        if row["基准层级"] == "服务器类型 × 用户来源"
        else f"{row['服务器类型']}大组",
        axis=1,
    )

    benchmark_lookup: dict[str, dict[str, float | int]] = {}

    def store_benchmark(benchmark_name: str, group: pd.DataFrame) -> None:
        benchmark_lookup[benchmark_name] = {
            "基准样本数": int(len(group)),
            "分组稳健均值": _trimmed_mean(group["近一周充值"], float(rules["trim_ratio"])),
            "分组充值P80": float(group["近一周充值"].quantile(float(rules["red_group_percentile"]))),
            "分组累计充值P80": float(group["累计充值"].quantile(float(rules["high_value_percentile"]))),
        }

    # The fallback pool must contain the entire old/new-server population, not
    # only the small subgroup that requested the fallback.
    for server_type, group in output.groupby("服务器类型", sort=False):
        store_benchmark(f"{server_type}大组", group)
    for (server_type, user_source), group in output.groupby(
        ["服务器类型", "用户来源"], sort=False
    ):
        if len(group) >= minimum_group_size:
            store_benchmark(f"{server_type} × {user_source}", group)
    for column in ("基准样本数", "分组稳健均值", "分组充值P80", "分组累计充值P80"):
        output[column] = output["基准范围"].map(
            {key: values[column] for key, values in benchmark_lookup.items()}
        )

    output["服务器平均充值"] = output["分组稳健均值"].astype(float)
    output["充值倍率"] = output.apply(
        lambda row: float(row["近一周充值"]) / float(row["分组稳健均值"])
        if float(row["分组稳健均值"]) > 0
        else 0.0,
        axis=1,
    )
    output["偏离率"] = output["充值倍率"] - 1.0
    output["个人变化率"] = output.apply(
        lambda row: float(row["近一周充值"]) / float(row["过去28日周均充值"]) - 1.0
        if pd.notna(row["过去28日周均充值"]) and float(row["过去28日周均充值"]) > 0
        else pd.NA,
        axis=1,
    )
    output["前7日变化率"] = output.apply(
        lambda row: float(row["近一周充值"]) / float(row["前7日充值"]) - 1.0
        if pd.notna(row["前7日充值"]) and float(row["前7日充值"]) > 0
        else pd.NA,
        axis=1,
    )
    high_value_floor = output["服务器类型"].map(rules["high_value_minimum"]).fillna(0.0)
    output["高价值门槛"] = pd.concat(
        [output["分组累计充值P80"].astype(float), high_value_floor.astype(float)], axis=1
    ).max(axis=1)
    output["高价值玩家"] = output["累计充值"] >= output["高价值门槛"]
    output["低于均值比例"] = output.apply(
        lambda row: max(
            0.0,
            (float(row["分组稳健均值"]) - float(row["近一周充值"]))
            / float(row["分组稳健均值"]),
        )
        if float(row["分组稳健均值"]) > 0
        else 0.0,
        axis=1,
    )
    output["充值下降比例"] = output.apply(
        lambda row: max(
            0.0,
            (float(row["过去28日周均充值"]) - float(row["近一周充值"]))
            / float(row["过去28日周均充值"]),
        )
        if pd.notna(row["过去28日周均充值"]) and float(row["过去28日周均充值"]) > 0
        else 0.0,
        axis=1,
    )

    original_counts = output.groupby("原始分组").size().to_dict()
    rows: list[dict[str, Any]] = []
    for server_type in ("老服", "新服"):
        for user_source in ("自然量", "CPS"):
            original_group = f"{server_type} × {user_source}"
            sample = output[
                (output["服务器类型"] == server_type)
                & (output["用户来源"] == user_source)
            ]
            benchmark_range = (
                original_group
                if len(sample) >= minimum_group_size
                else f"{server_type}大组"
            )
            metrics = benchmark_lookup.get(
                benchmark_range,
                {"基准样本数": 0, "分组稳健均值": 0.0, "分组充值P80": 0.0, "分组累计充值P80": 0.0},
            )
            rows.append(
                {
                    "原始分组": original_group,
                    "原始样本数": int(original_counts.get(original_group, 0)),
                    "采用基准范围": benchmark_range,
                    **metrics,
                }
            )
    return output, pd.DataFrame(rows)


def _trimmed_mean(values: pd.Series, trim_ratio: float) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna().sort_values().reset_index(drop=True)
    if numeric.empty:
        return 0.0
    trim_count = int(len(numeric) * max(0.0, min(trim_ratio, 0.49)))
    if trim_count > 0 and trim_count * 2 < len(numeric):
        numeric = numeric.iloc[trim_count:-trim_count]
    return float(numeric.mean()) if not numeric.empty else 0.0


def _build_red_candidates(df: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    minimum_payment = df["服务器类型"].map(rules["red_minimum_payment"]).fillna(float("inf"))
    red = df[
        (df["趋势状态"] == "可比较")
        & (df["近一周充值"] >= minimum_payment)
        & (df["充值倍率"] >= float(rules["red_group_multiplier"]))
        & (df["近一周充值"] >= df["分组充值P80"])
        & (df["个人变化率"].astype("Float64") >= float(rules["red_personal_growth_ratio"]))
    ].copy()
    if red.empty:
        return red
    red["红榜评级"] = red.apply(_red_rating, axis=1)
    red["运营建议"] = red["红榜评级"].map(
        {
            "超级红榜": "重点维护，优先安排高价值回访",
            "红榜": "跟进消费增长原因，匹配高阶权益",
            "关注": "保持轻触达，观察增长能否延续",
        }
    )
    return red.sort_values(
        ["个人变化率", "充值倍率", "近一周充值"], ascending=[False, False, False]
    )


def _build_black_candidates(
    df: pd.DataFrame,
    red_candidates: pd.DataFrame,
    rules: dict[str, Any],
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    red_keys = set(red_candidates["_玩家键"].astype(str)) if not red_candidates.empty else set()
    risk_signal = (
        df["充值下降比例"] >= float(rules["black_personal_decline_ratio"])
    ) | df["零充值信号"]
    black = df[
        ~df["_玩家键"].astype(str).isin(red_keys)
        & df["高价值玩家"]
        & (df["趋势状态"] == "可比较")
        & risk_signal
    ].copy()
    if black.empty:
        return black
    black["风险指数"] = black.apply(lambda row: _black_risk_score(row, rules), axis=1)
    black["风险等级"] = black["风险指数"].map(lambda score: _black_risk_level(score, rules))
    black["运营建议"] = black["风险等级"].map(
        {
            "高风险": "优先人工触达，确认沉默与消费下降原因",
            "中风险": "安排召回沟通，匹配回流权益",
            "观察": "暂不强触达，关注下周充值与登录变化",
        }
    )
    return black.sort_values(["风险指数", "累计充值"], ascending=[False, False])


def _build_observation_list(
    df: pd.DataFrame,
    red_candidates: pd.DataFrame,
    black_candidates: pd.DataFrame,
    rules: dict[str, Any],
) -> pd.DataFrame:
    excluded_keys = set(red_candidates.get("_玩家键", pd.Series(dtype=str)).astype(str))
    excluded_keys.update(black_candidates.get("_玩家键", pd.Series(dtype=str)).astype(str))
    observe_days = int(rules["login_risk_start_days"])
    high_days = int(rules["login_high_risk_days"])
    login_window = df["最后登录间隔"].between(observe_days, high_days - 1)
    payment_window = (
        df["近一周充值"].le(0)
        & df["前7日充值"].fillna(0).gt(0)
    )
    observation = df[
        (df["趋势状态"] == "观察期") | login_window | payment_window
    ].copy()
    if excluded_keys:
        observation = observation[~observation["_玩家键"].astype(str).isin(excluded_keys)].copy()
    if observation.empty:
        return observation
    observation["观察原因"] = observation.apply(
        lambda row: _observation_reason(row, observe_days, high_days),
        axis=1,
    )
    observation["风险指数"] = observation.apply(
        lambda row: _black_risk_score(row, rules),
        axis=1,
    )
    observation["风险等级"] = observation["风险指数"].map(
        lambda score: _black_risk_level(score, rules)
    )
    observation["运营建议"] = observation["风险等级"].map(
        {
            "高风险": "优先核查登录与充值窗口，必要时升级触达",
            "中风险": "保持人工观察，等待下一个 7 日窗口确认",
            "观察": "暂不强触达，持续观察登录与充值变化",
        }
    )
    return observation.sort_values(
        ["风险指数", "累计充值", "近一周充值"],
        ascending=[False, False, False],
    )


def _observation_reason(row: pd.Series, observe_days: int, high_days: int) -> str:
    reasons: list[str] = []
    if str(row.get("趋势状态") or "") == "观察期":
        reasons.append(
            {
                "数据缺失": "缺少前 7 日或过去 28 日充值字段",
                "新增充值无历史基线": "本周新增充值但暂无历史基线",
            }.get(str(row.get("基线类型") or ""), "个人趋势暂不可比较")
        )
    inactivity_days = int(row.get("最后登录间隔") or 0)
    if observe_days <= inactivity_days < high_days:
        reasons.append(f"距最后登录 {inactivity_days} 天，处于 {observe_days}–{high_days - 1} 天观察窗口")
    previous = pd.to_numeric(row.get("前7日充值"), errors="coerce")
    current = pd.to_numeric(row.get("近一周充值"), errors="coerce")
    if pd.notna(previous) and float(previous) > 0 and pd.notna(current) and float(current) <= 0:
        reasons.append("近 7 日未充值，等待 14 日窗口确认")
    return "；".join(reasons) or "进入 7 日观察窗口"


def _red_rating(row: pd.Series) -> str:
    growth = float(row["个人变化率"])
    multiplier = float(row["充值倍率"])
    if growth >= 1.0 and multiplier >= 3.0:
        return "超级红榜"
    if growth >= 0.5 or multiplier >= 2.0:
        return "红榜"
    return "关注"


def _black_risk_score(row: pd.Series, rules: dict[str, Any]) -> float:
    has_positive_baseline = (
        pd.notna(row["过去28日周均充值"])
        and float(row["过去28日周均充值"]) > 0
    )
    previous_payment = pd.to_numeric(row.get("前7日充值"), errors="coerce")
    continuous_zero = (
        bool(row["零充值信号"])
        and pd.notna(previous_payment)
        and float(previous_payment) <= 0
    )
    if continuous_zero:
        decline_component = float(rules["payment_zero_14d_score"])
    elif bool(row["零充值信号"]):
        decline_component = float(rules["payment_zero_7d_score"])
    elif not has_positive_baseline:
        decline_component = float(rules["black_zero_payment_signal_score"])
    else:
        decline_component = min(
            50.0, max(0.0, float(row["充值下降比例"])) * 50.0
        )
    login_days = int(row["最后登录间隔"])
    if login_days >= int(rules["login_high_risk_days"]):
        login_component = float(rules["login_high_risk_score"])
    elif login_days >= int(rules["login_risk_start_days"]):
        login_component = float(rules["login_observe_score"])
    else:
        login_component = 0.0
    threshold = max(float(row["高价值门槛"]), 1.0)
    value_ratio = float(row["累计充值"]) / threshold
    value_component = min(20.0, 10.0 + max(0.0, value_ratio - 1.0) * 10.0)
    return round(min(100.0, decline_component + login_component + value_component), 2)


def _black_risk_level(score: float, rules: dict[str, Any]) -> str:
    if float(score) >= float(rules["risk_high_threshold"]):
        return "高风险"
    if float(score) >= float(rules["risk_medium_threshold"]):
        return "中风险"
    return "观察"


def _top_display(dataframe: pd.DataFrame, top_n: int) -> pd.DataFrame:
    display = dataframe.head(max(int(top_n), 0)).copy().reset_index(drop=True)
    if display.empty:
        return display
    if "排名" in display.columns:
        display = display.drop(columns=["排名"])
    display.insert(0, "排名", range(1, len(display) + 1))
    return display
