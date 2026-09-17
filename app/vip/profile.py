from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.vip.server_merges import canonical_server_id, normalize_server_id


CONFIG_DIR = Path(__file__).parent / "config"
SERVER_OPEN_DATES_PATH = CONFIG_DIR / "server_open_dates.json"
CULTIVATION_PATHS_PATH = CONFIG_DIR / "cultivation_paths.json"

POWER_FIELDS = {
    "build_fp": "建筑战力",
    "tech_fp": "科技战力",
    "soldier_fp": "士兵战力",
    "beast_fp": "巨兽战力",
    "hero_fp": "指挥官战力",
    "hiryu_fp": "飞龙战力",
    "com_fp": "统帅战力",
    "leg_tech_fp": "军团科技战力",
    "cur_fp": "当前总战力",
}

POWER_FIELD_CATEGORIES = {
    "建筑发展": "build_fp",
    "科研发展": "tech_fp",
    "士兵养成": "soldier_fp",
    "巨兽养成": "beast_fp",
    "巨兽机甲": "beast_fp",
    "神兽养成": "beast_fp",
    "天启养成": "beast_fp",
    "装备强化": "hero_fp",
    "徽章养成": "hero_fp",
    "飞龙养成": "hiryu_fp",
    "统帅养成": "com_fp",
}

PROFILE_CATEGORIES = tuple(POWER_FIELD_CATEGORIES) + ("通用资源", "其他")


@dataclass(frozen=True)
class ServerStage:
    server_id: str
    label: str
    open_date: date | None
    age_days: int | None
    fully_unlocked: bool
    known: bool


@dataclass(frozen=True)
class ProfileCoverage:
    recharge: bool
    purchases: bool
    power: bool

    @property
    def available_count(self) -> int:
        return sum((self.recharge, self.purchases, self.power))

    @property
    def total_count(self) -> int:
        return 3

    @property
    def ratio(self) -> float:
        return self.available_count / self.total_count


@dataclass(frozen=True)
class PowerGap:
    category: str
    field: str
    label: str
    player_share: float
    peer_median_share: float
    gap_ratio: float
    peer_count: int


@dataclass(frozen=True)
class DemandSignal:
    category: str
    score: float
    recent_amount: float
    lifetime_amount: float
    purchase_count: int
    recent_share: float
    lifetime_share: float
    gap_ratio: float
    stage_score: float
    packages: tuple[str, ...]
    items: tuple[str, ...]


@dataclass(frozen=True)
class ProfileInsight:
    coverage: ProfileCoverage
    recommendations: tuple[DemandSignal, ...]
    power_gaps: tuple[PowerGap, ...]
    confidence: str

    @property
    def primary(self) -> DemandSignal | None:
        return self.recommendations[0] if self.recommendations else None


def load_server_open_dates(path: str | Path = SERVER_OPEN_DATES_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_cultivation_paths(path: str | Path = CULTIVATION_PATHS_PATH) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("paths", []))


def server_stage(server_value: object, *, as_of: datetime | date | None = None) -> ServerStage:
    normalized = normalize_server_id(server_value)
    primary = canonical_server_id(normalized)
    label = f"S{primary}" if primary.isdigit() else (primary or "未识别区服")
    config = load_server_open_dates()
    fully_unlocked = normalized in set(config.get("fully_unlocked_servers", []))
    if fully_unlocked:
        return ServerStage(primary, label, None, None, True, True)

    open_date_text = str(config.get("servers", {}).get(primary) or "")
    if not open_date_text:
        return ServerStage(primary, label, None, None, False, False)
    open_date = date.fromisoformat(open_date_text)
    reference = as_of.date() if isinstance(as_of, datetime) else (as_of or date.today())
    age_days = max((reference - open_date).days + 1, 0)
    return ServerStage(primary, label, open_date, age_days, False, True)


def cultivation_progress(
    server_value: object,
    *,
    as_of: datetime | date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stage = server_stage(server_value, as_of=as_of)
    unlocked: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    conditional: list[dict[str, Any]] = []
    for source in load_cultivation_paths():
        item = dict(source)
        unlock_day = item.get("unlock_day")
        if item.get("available", True) is False or unlock_day is None:
            item["status"] = "前置条件"
            conditional.append(item)
            continue
        if stage.fully_unlocked or (stage.age_days is not None and stage.age_days >= int(unlock_day)):
            item["status"] = "已开放"
            unlocked.append(item)
        else:
            item["status"] = "待开放"
            item["days_remaining"] = max(int(unlock_day) - int(stage.age_days or 0), 0)
            upcoming.append(item)
    upcoming.sort(key=lambda item: int(item.get("unlock_day") or 10**9))
    return unlocked, upcoming, conditional


def profile_coverage(player: pd.Series, purchase_rows: pd.DataFrame | None = None) -> ProfileCoverage:
    recharge_columns = ("累计充值", "近一周充值", "前7日充值")
    recharge = any(column in player.index and pd.notna(player.get(column)) for column in recharge_columns)
    power_values = [
        _number(player.get(field))
        for field in POWER_FIELDS
        if field in player.index and pd.notna(player.get(field))
    ]
    power = len(power_values) >= 3 and any(value > 0 for value in power_values)
    purchases = purchase_rows is not None and not purchase_rows.empty
    return ProfileCoverage(recharge=recharge, purchases=purchases, power=power)


def payment_direction(player: pd.Series) -> tuple[str, str]:
    current = _number(player.get("近一周充值"))
    previous = _number(player.get("前7日充值"))
    if current <= 0 and previous <= 0:
        return "连续两周无充值", "近 7 日与前 7 日充值均为 0"
    if previous <= 0 < current:
        return "近期恢复付费", f"近 7 日充值 {current:,.2f}"
    change = (current - previous) / previous if previous else 0.0
    if change >= 0.2:
        return "付费升温", f"较前 7 日上升 {change:.0%}"
    if change <= -0.2:
        return "付费降温", f"较前 7 日下降 {abs(change):.0%}"
    return "付费稳定", f"近 7 日 {current:,.2f}，前 7 日 {previous:,.2f}"


def recommendation_state(
    coverage: ProfileCoverage,
    insight: ProfileInsight | None = None,
) -> tuple[str, str, str]:
    if not coverage.purchases and not coverage.power:
        return (
            "画像证据待同步",
            "当前只能判断付费节奏，尚不能确定具体消费内容。",
            "pending",
        )
    if not coverage.purchases:
        return (
            "礼包偏好待补齐",
            "已有分项战力，但缺少真实礼包和道具购买记录。",
            "partial",
        )
    if not coverage.power:
        return (
            "需求缺口待补齐",
            "已有购买偏好，但缺少同阶段分项战力差距。",
            "partial",
        )
    if insight is not None and insight.primary is not None:
        primary = insight.primary
        gap_copy = (
            f"对应分项低于同阶段中位水平 {primary.gap_ratio:.0%}。"
            if primary.gap_ratio > 0
            else "对应分项未发现明显落后。"
        )
        return (
            primary.category,
            f"需求方向指数 {primary.score:.0f}；近 30 日实付 {primary.recent_amount:,.2f}。{gap_copy}",
            "ready",
        )
    return ("画像证据已具备", "购买偏好与分项战力均可用于计算需求方向。", "ready")


def build_profile_insight(
    player: pd.Series,
    purchase_rows: pd.DataFrame | None,
    cohort: pd.DataFrame,
    *,
    as_of: datetime | date | None = None,
) -> ProfileInsight:
    coverage = profile_coverage(player, purchase_rows)
    gaps = tuple(calculate_power_gaps(player, cohort, as_of=as_of)) if coverage.power else ()
    if not coverage.purchases or not coverage.power or purchase_rows is None:
        return ProfileInsight(coverage, (), gaps, "证据不足")

    purchases = _purchase_category_summary(purchase_rows)
    if purchases.empty:
        return ProfileInsight(coverage, (), gaps, "证据不足")
    gap_by_field = {gap.field: gap for gap in gaps}
    recent_total = float(
        purchases.loc[purchases["window_key"].eq("recent_30d"), "payment_amount"].sum()
    )
    lifetime_total = float(
        purchases.loc[purchases["window_key"].eq("lifetime"), "payment_amount"].sum()
    )
    lifetime_count = float(
        purchases.loc[purchases["window_key"].eq("lifetime"), "purchase_count"].sum()
    )
    categories = set(purchases["category"].astype(str))
    categories.update(
        category
        for category, field in POWER_FIELD_CATEGORIES.items()
        if gap_by_field.get(field) is not None and gap_by_field[field].gap_ratio >= 0.08
    )
    signals: list[DemandSignal] = []
    for category in categories:
        category_rows = purchases[purchases["category"].eq(category)]
        recent_rows = category_rows[category_rows["window_key"].eq("recent_30d")]
        lifetime_rows = category_rows[category_rows["window_key"].eq("lifetime")]
        recent_amount = float(recent_rows["payment_amount"].sum())
        lifetime_amount = float(lifetime_rows["payment_amount"].sum())
        purchase_count = int(round(float(lifetime_rows["purchase_count"].sum())))
        recent_share = recent_amount / recent_total if recent_total > 0 else 0.0
        lifetime_share = lifetime_amount / lifetime_total if lifetime_total > 0 else 0.0
        count_share = purchase_count / lifetime_count if lifetime_count > 0 else 0.0
        purchase_score = 0.55 * recent_share + 0.25 * lifetime_share + 0.20 * count_share
        power_field = POWER_FIELD_CATEGORIES.get(category)
        gap_ratio = gap_by_field.get(power_field).gap_ratio if power_field in gap_by_field else 0.0
        stage_score = _category_stage_score(category, player.get("区服"), as_of=as_of)
        category_reliability = {"其他": 0.42, "通用资源": 0.70}.get(category, 1.0)
        score = (
            100.0
            * (0.55 * purchase_score + 0.35 * gap_ratio + 0.10 * stage_score)
            * category_reliability
        )
        packages, items = _category_examples(category_rows)
        signals.append(
            DemandSignal(
                category=category,
                score=round(score, 1),
                recent_amount=recent_amount,
                lifetime_amount=lifetime_amount,
                purchase_count=purchase_count,
                recent_share=recent_share,
                lifetime_share=lifetime_share,
                gap_ratio=gap_ratio,
                stage_score=stage_score,
                packages=packages,
                items=items,
            )
        )
    signals.sort(
        key=lambda signal: (
            -signal.score,
            -signal.recent_amount,
            -signal.lifetime_amount,
            signal.category,
        )
    )
    recommendations = tuple(signals[:3])
    if not recommendations:
        confidence = "证据不足"
    else:
        margin = recommendations[0].score - (recommendations[1].score if len(recommendations) > 1 else 0)
        confidence = "较高" if recommendations[0].score >= 55 and margin >= 8 else "中等"
    return ProfileInsight(coverage, recommendations, gaps, confidence)


def calculate_power_gaps(
    player: pd.Series,
    cohort: pd.DataFrame,
    *,
    as_of: datetime | date | None = None,
) -> list[PowerGap]:
    if cohort.empty:
        return []
    eligible = cohort.copy()
    if "角色ID" in eligible.columns and "角色ID" in player.index:
        eligible = eligible[
            eligible["角色ID"].astype(str).ne(str(player.get("角色ID") or ""))
        ]
    if eligible.empty:
        return []
    target_bucket = _stage_bucket(player.get("区服"), as_of=as_of)
    peer_frame = eligible[
        eligible["区服"].map(lambda value: _stage_bucket(value, as_of=as_of)).eq(target_bucket)
    ].copy()
    if len(peer_frame) < 5 and "服务器类型" in eligible.columns:
        server_type = str(player.get("服务器类型") or "")
        peer_frame = eligible[eligible["服务器类型"].astype(str).eq(server_type)].copy()
    if len(peer_frame) < 5:
        peer_frame = eligible.copy()

    component_fields = tuple(field for field in POWER_FIELDS if field != "cur_fp")
    peer_denominators = peer_frame.apply(_power_denominator, axis=1)
    player_denominator = _power_denominator(player)
    if player_denominator <= 0:
        return []
    output: list[PowerGap] = []
    for field in component_fields:
        if field not in peer_frame.columns or field not in player.index:
            continue
        ratios = pd.to_numeric(peer_frame[field], errors="coerce").fillna(0).div(
            peer_denominators.replace(0, pd.NA)
        ).dropna()
        positive = ratios[ratios >= 0]
        if positive.empty:
            continue
        median_share = float(positive.median())
        if median_share <= 0:
            continue
        player_share = _number(player.get(field)) / player_denominator
        gap_ratio = min(max((median_share - player_share) / median_share, 0.0), 1.0)
        if gap_ratio <= 0:
            continue
        category = next(
            (name for name, mapped_field in POWER_FIELD_CATEGORIES.items() if mapped_field == field),
            POWER_FIELDS[field],
        )
        output.append(
            PowerGap(
                category=category,
                field=field,
                label=POWER_FIELDS[field],
                player_share=player_share,
                peer_median_share=median_share,
                gap_ratio=gap_ratio,
                peer_count=int(len(positive)),
            )
        )
    output.sort(key=lambda gap: (-gap.gap_ratio, gap.label))
    return output


def _purchase_category_summary(rows: pd.DataFrame) -> pd.DataFrame:
    output = rows.copy()
    defaults: dict[str, object] = {
        "window_key": "",
        "category": "其他",
        "giftbox_name": "未命名礼包",
        "purchase_count": 0,
        "payment_amount": 0.0,
        "items_json": "[]",
    }
    for column, default in defaults.items():
        if column not in output.columns:
            output[column] = default
    output["purchase_count"] = pd.to_numeric(output["purchase_count"], errors="coerce").fillna(0)
    output["payment_amount"] = pd.to_numeric(output["payment_amount"], errors="coerce").fillna(0.0)
    output["category"] = output["category"].fillna("其他").astype(str)
    return output


def _category_examples(rows: pd.DataFrame) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if rows.empty:
        return (), ()
    ranked = rows.copy()
    ranked["window_rank"] = ranked["window_key"].map({"recent_30d": 0, "lifetime": 1}).fillna(2)
    ranked = ranked.sort_values(
        ["window_rank", "payment_amount", "purchase_count"],
        ascending=[True, False, False],
        kind="stable",
    )
    packages: list[str] = []
    items: list[str] = []
    for _, row in ranked.iterrows():
        giftbox_name, _ = giftbox_display_name(
            row.get("giftbox_name"),
            row.get("giftbox_id"),
        )
        if giftbox_name and giftbox_name not in packages:
            packages.append(giftbox_name)
        try:
            item_payload = json.loads(str(row.get("items_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            item_payload = []
        if isinstance(item_payload, list):
            for item in item_payload:
                if not isinstance(item, dict):
                    continue
                item_name = str(item.get("item_name") or "").strip()
                if item_name and item_name not in items:
                    items.append(item_name)
        if len(packages) >= 3 and len(items) >= 4:
            break
    return tuple(packages[:3]), tuple(items[:4])


def giftbox_display_name(
    giftbox_name: object,
    giftbox_id: object,
) -> tuple[str, bool]:
    name = str(giftbox_name or "").strip()
    missing = not name or name == "未命名礼包" or name.endswith("（名称待补充）")
    if not missing:
        return name, False

    identifier = str(giftbox_id or "").strip().split("::", 1)[0]
    if identifier and not identifier.startswith("name:"):
        return f"礼包 ID {identifier}", True
    return "礼包名称待补充", True


def _category_stage_score(
    category: str,
    server_value: object,
    *,
    as_of: datetime | date | None,
) -> float:
    if category in {"通用资源", "其他"}:
        return 0.55
    keywords = {
        "建筑发展": ("城建", "建筑"),
        "科研发展": ("科研", "超导科技"),
        "士兵养成": ("士兵",),
        "巨兽养成": ("巨兽", "基因", "源晶"),
        "巨兽机甲": ("巨兽机甲",),
        "神兽养成": ("神兽",),
        "天启养成": ("天启",),
        "装备强化": ("装备",),
        "徽章养成": ("徽章",),
        "飞龙养成": ("飞龙", "龙鳞", "翼装"),
        "统帅养成": ("统帅",),
    }.get(category, ())
    unlocked, upcoming, conditional = cultivation_progress(server_value, as_of=as_of)
    if any(any(keyword in str(item.get("name")) for keyword in keywords) for item in unlocked):
        return 1.0
    relevant_upcoming = [
        item
        for item in upcoming
        if any(keyword in str(item.get("name")) for keyword in keywords)
    ]
    if relevant_upcoming:
        nearest = min(int(item.get("days_remaining") or 0) for item in relevant_upcoming)
        return 0.72 if nearest <= 14 else 0.18
    if any(any(keyword in str(item.get("name")) for keyword in keywords) for item in conditional):
        return 0.32
    return 0.2


def _stage_bucket(server_value: object, *, as_of: datetime | date | None) -> str:
    stage = server_stage(server_value, as_of=as_of)
    if stage.fully_unlocked:
        return "fully_unlocked"
    if stage.age_days is None:
        return "unknown"
    boundaries = (35, 60, 90, 151, 180, 240, 300, 360)
    lower = 1
    for upper in boundaries:
        if stage.age_days < upper:
            return f"{lower}-{upper - 1}"
        lower = upper
    return "360+"


def _power_denominator(player: pd.Series) -> float:
    total = _number(player.get("cur_fp"))
    if total > 0:
        return total
    return sum(
        _number(player.get(field))
        for field in POWER_FIELDS
        if field != "cur_fp"
    )


def player_option_label(player: pd.Series) -> str:
    role_name = str(player.get("角色名") or "").strip() or "未命名玩家"
    role_id = str(player.get("角色ID") or "").strip() or "-"
    stage = server_stage(player.get("区服"))
    return f"{role_name} · {stage.label} · {role_id}"


def _number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(number) else number
