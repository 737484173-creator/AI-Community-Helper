from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.vip.scoring.new_server_cps import score_player as score_new_server_cps
from app.vip.scoring.new_server_organic import score_player as score_new_server_organic
from app.vip.scoring.old_server_cps import score_player as score_old_server_cps
from app.vip.scoring.old_server_organic import score_player as score_old_server_organic


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "scoring_rules.json"


def load_scoring_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    """读取评分规则配置，金额区间和评级阈值统一放在 JSON 中维护。"""
    try:
        with Path(path).open("r", encoding="utf-8") as rule_file:
            return json.load(rule_file)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"评分规则文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"评分规则文件格式错误：{path}") from exc


def score_dataframe(df: pd.DataFrame, rules: dict[str, Any] | None = None, as_of: datetime | None = None) -> pd.DataFrame:
    """为整张 VIP 表添加玩家分组、价值分、风险分、触达优先级和原因。"""
    result = df.copy()
    active_rules = rules or load_scoring_rules()
    effective_as_of = as_of or datetime.now()
    score_rows = [score_row(row, active_rules, effective_as_of) for _, row in result.iterrows()]
    score_df = pd.DataFrame(score_rows)
    return pd.concat([result.reset_index(drop=True), score_df.reset_index(drop=True)], axis=1)


def score_row(row: pd.Series, rules: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    """根据服务器类型和用户来源路由到三套独立评分函数。"""
    try:
        group = classify_player(row)
        if group == "老服自然量":
            return score_old_server_organic(row, rules["old_server_organic"], rules, as_of)
        if group == "老服CPS":
            return score_old_server_cps(row, rules["old_server_cps"], rules, as_of)
        if group == "新服自然量":
            return score_new_server_organic(row, rules["new_server_organic"], rules, as_of)
        if group == "新服CPS":
            return score_new_server_cps(row, rules["new_server_cps"], rules, as_of)
        return unclassified_score("服务器类型或用户来源缺失")
    except Exception as exc:
        return unclassified_score(f"评分异常：{exc}")


def classify_player(row: pd.Series) -> str:
    """识别玩家所属业务分组，无法识别时返回“未分类”。"""
    server_type = normalize_text(row.get("服务器类型"))
    user_source = normalize_text(row.get("用户来源")).upper()
    if server_type == "老服" and user_source in {"自然量", "NATURAL"}:
        return "老服自然量"
    if server_type == "老服" and user_source == "CPS":
        return "老服CPS"
    if server_type == "新服" and user_source in {"自然量", "NATURAL"}:
        return "新服自然量"
    if server_type == "新服" and user_source == "CPS":
        return "新服CPS"
    return "未分类"


def unclassified_score(reason: str) -> dict[str, Any]:
    """返回无法分类记录的兜底结果，避免页面因脏数据中断。"""
    return {
        "玩家分组": "未分类",
        "价值分": 0,
        "风险分": 0,
        "触达优先级": "数据异常：无法识别服务器类型或用户来源",
        "原因": reason,
    }


def normalize_text(value: Any) -> str:
    """统一清理文本字段，兼容空值。"""
    if pd.isna(value):
        return ""
    return str(value).strip()
