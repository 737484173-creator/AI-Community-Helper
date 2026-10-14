"""Read the dated, one-time review of historical rejected applications.

The review is evidence, not an approval queue.  New applications continue through
the normal Discord/member-review flow and are never modified by this module.
"""

from __future__ import annotations

import csv
from pathlib import Path


RECHECK_DATE = "2026-09-20"
PRIORITY_CATEGORIES = frozenset(
    {"旧区服误拒候选", "远端原文待核", "区服格式待人工确认"}
)
RECHECK_CATEGORIES = (
    "旧区服误拒候选",
    "远端原文待核",
    "区服格式待人工确认",
    "已开服但缺角色名",
    "表单已核实仍不符合",
    "区服仍异常",
    "内容仍不完整",
)


def recheck_snapshot_path(db_path: str | Path) -> Path:
    return Path(db_path).parent / "reviews" / f"rejected_review_full_{RECHECK_DATE}.csv"


def load_recheck_snapshot(path: Path) -> dict[int, dict[str, str]]:
    """Index audited records by application ID; fail clearly on missing/bad data."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"申请ID", "复核分类", "Discord用户ID"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("历史拒绝复核文件缺少必要字段")
        result: dict[int, dict[str, str]] = {}
        for row in reader:
            application_id = int(row["申请ID"])
            if application_id in result:
                raise ValueError(f"历史拒绝复核文件存在重复申请 ID：{application_id}")
            result[application_id] = row
    return result
