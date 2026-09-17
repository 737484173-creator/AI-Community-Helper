from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from app.vip.scoring.common import login_days, payment_risk, priority, reason_text, score_by_ranges, to_float


def score_player(row: pd.Series, rules: dict[str, Any], global_rules: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    """新服CPS评分：使用独立CPS价值阈值和近期充值阈值。"""
    try:
        cumulative = to_float(row.get("累计充值"))
        weekly = to_float(row.get("近一周充值"))
        cumulative_score = score_by_ranges(cumulative, rules["cumulative_value_ranges"])
        recent_score = score_by_ranges(weekly, rules["recent_value_ranges"])
        value_score = cumulative_score + recent_score
        inactivity_days = login_days(row.get("最后登录时间"), as_of)
        login_risk = score_by_ranges(inactivity_days, rules["login_risk_ranges"])
        recharge_risk, payment_reason = payment_risk(row, global_rules)
        risk_score = login_risk + recharge_risk
        return {
            "玩家分组": "新服CPS",
            "价值分": value_score,
            "风险分": risk_score,
            "触达优先级": priority(value_score + risk_score, global_rules),
            "原因": reason_text(
                value_score,
                risk_score,
                weekly,
                login_risk,
                inactivity_days=inactivity_days,
                payment_reason=payment_reason,
            ),
        }
    except Exception as exc:
        return {"玩家分组": "新服CPS", "价值分": 0, "风险分": 0, "触达优先级": f"评分异常：{exc}", "原因": "新服CPS评分异常"}
