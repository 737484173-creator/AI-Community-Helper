from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def score_by_ranges(value: float, ranges: list[dict[str, Any]]) -> int:
    """按从高到低的金额或天数区间返回分数。"""
    for rule in ranges:
        if value >= float(rule["min"]):
            return int(rule["score"])
    return 0


def login_days(last_login: Any, as_of: datetime) -> int:
    """计算距离最后登录的天数，无法识别时间时按最高风险处理。"""
    login_time = pd.to_datetime(last_login, errors="coerce")
    if pd.isna(login_time):
        return 999
    return max((as_of - login_time.to_pydatetime()).days, 0)


def priority(total_score: int, global_rules: dict[str, Any]) -> str:
    """按总分阈值输出触达优先级。"""
    for rule in global_rules.get("priority_thresholds", []):
        if total_score >= int(rule["min"]):
            return str(rule["label"])
    return "暂不触达"


def payment_risk(
    row: Any,
    global_rules: dict[str, Any],
) -> tuple[int, str]:
    """Score the current 7-day payment window against the preceding 7 days."""
    rules = global_rules.get("payment_risk", {})
    current = to_float(row.get("近一周充值"))
    previous = optional_float(row.get("前7日充值"))
    cumulative = to_float(row.get("累计充值"))
    if cumulative <= 0:
        return 0, ""

    if previous is None:
        if current <= 0:
            return int(rules.get("zero_7d_score", 20)), "近 7 日未充值"
        return 0, ""
    if current <= 0 and previous <= 0:
        return int(rules.get("zero_14d_score", 35)), "连续 14 日未充值"
    if current <= 0:
        return int(rules.get("zero_7d_score", 20)), "近 7 日未充值"
    if previous <= 0:
        return 0, ""

    decline_ratio = max(0.0, (previous - current) / previous)
    high_ratio = float(rules.get("high_decline_ratio", 0.5))
    observe_ratio = float(rules.get("observe_decline_ratio", 0.25))
    if decline_ratio >= high_ratio:
        return int(rules.get("high_decline_score", 20)), "近 7 日充值较前 7 日明显下降"
    if decline_ratio >= observe_ratio:
        return int(rules.get("observe_decline_score", 10)), "近 7 日充值较前 7 日下降"
    return 0, ""


def reason_text(
    value_score: int,
    risk_score: int,
    weekly_recharge: float,
    login_risk: int,
    *,
    inactivity_days: int | None = None,
    payment_reason: str = "",
) -> str:
    """生成运营可读的触达原因。"""
    reasons: list[str] = []
    if value_score >= 35:
        reasons.append("高价值")
    if payment_reason:
        reasons.append(payment_reason)
    elif weekly_recharge == 0:
        reasons.append("近 7 日未充值")
    if inactivity_days is not None and inactivity_days >= 14:
        reasons.append("已 14 天以上未登录")
    elif inactivity_days is not None and inactivity_days >= 7:
        reasons.append("已 7 天以上未登录，进入观察")
    elif login_risk >= 20:
        reasons.append("登录风险上升")
    if risk_score >= 50 and not any("登录" in reason for reason in reasons):
        reasons.append("活跃风险较高")
    return "、".join(reasons) if reasons else "消费与活跃相对稳定"


def to_float(value: Any) -> float:
    """将 Excel 中的金额字段安全转为浮点数。"""
    number = pd.to_numeric(value, errors="coerce")
    return 0.0 if pd.isna(number) else float(number)


def optional_float(value: Any) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(number) else float(number)
