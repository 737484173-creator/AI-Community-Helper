from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from config.settings import BASE_DIR


DEFAULT_ITEM_CATALOG_PATH = BASE_DIR / "data" / "vip" / "D-道具表.xlsx"


@dataclass(frozen=True)
class ItemCatalog:
    items: dict[str, str]
    gifts: dict[str, str]
    source_path: str | None
    item_categories: dict[str, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.items or self.gifts)


@lru_cache(maxsize=4)
def load_item_catalog(path: str | Path | None = None) -> ItemCatalog:
    source = _catalog_path(path)
    if source is None:
        return ItemCatalog({}, {}, None)
    try:
        item_frame = pd.read_excel(
            source,
            sheet_name="DaojuBiao",
            usecols=["物品ID", "道具名", "名称后缀", "道具描述"],
        )
        gift_frame = pd.read_excel(
            source,
            sheet_name="GiftPackBiao",
            usecols=["道具ID", "名称", "名称后缀"],
        )
    except (OSError, ValueError):
        return ItemCatalog({}, {}, str(source))

    items: dict[str, str] = {}
    item_categories: dict[str, str] = {}
    for _, row in item_frame.iterrows():
        item_id = _identifier(row.get("物品ID"))
        name = _text(row.get("道具名"))
        if item_id and name:
            items[item_id] = name
            item_categories[item_id] = classify_consumption_category(
                name,
                row.get("名称后缀"),
                row.get("道具描述"),
            )

    gifts: dict[str, str] = {}
    for _, row in gift_frame.iterrows():
        gift_id = _identifier(row.get("道具ID"))
        base_name = _text(row.get("名称"))
        suffix = _text(row.get("名称后缀"))
        if gift_id and base_name:
            gifts[gift_id] = " ".join(part for part in (base_name, suffix) if part)
    return ItemCatalog(items, gifts, str(source), item_categories)


def classify_consumption_category(*labels: object) -> str:
    text = " ".join(_text(value) for value in labels if _text(value)).casefold()
    if not text:
        return "其他"
    rules = (
        ("神兽养成", ("神兽", "玄武", "白虎", "朱雀", "青龙")),
        ("天启养成", ("天启",)),
        ("飞龙养成", ("飞龙", "龙鳞", "翼装")),
        ("巨兽机甲", ("巨兽机甲", "机甲")),
        ("巨兽养成", ("巨兽", "基因", "源晶")),
        ("装备强化", ("装备", "指挥官装备", "装备升星", "洗练")),
        ("徽章养成", ("徽章",)),
        ("统帅养成", ("统帅",)),
        ("科研发展", ("科研", "科技", "研究")),
        ("建筑发展", ("建筑", "建造", "城建")),
        ("士兵养成", ("士兵", "招募令", "兵种", "单兵")),
    )
    for category, keywords in rules:
        if any(keyword.casefold() in text for keyword in keywords):
            return category
    if any(
        keyword in text
        for keyword in (
            "钢铁",
            "石油",
            "番茄",
            "钻石",
            "金币",
            "加速",
            "体力",
            "口粮",
            "vip经验",
            "贵族积分",
            "物资",
        )
    ):
        return "通用资源"
    return "其他"


def _catalog_path(path: str | Path | None) -> Path | None:
    configured = str(path or os.getenv("VIP_ITEM_CATALOG_PATH", "")).strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        (
            DEFAULT_ITEM_CATALOG_PATH,
            Path.home() / "Desktop" / "D-道具表.xlsx",
        )
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _identifier(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    return text.removesuffix(".0")


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none", "null", "(null)"} else text
