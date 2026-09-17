from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

from app.database.migrations.init_db import init_database
from app.database.repositories.vip_ae_repository import AEVIPSnapshotRepository
from app.vip.ae_sync import (
    CUMULATIVE_PROFILE_DEFINITION,
    FOURTEEN_DAY_PAYMENT_DEFINITION,
    ROLLING_28_DAY_PAYMENT_DEFINITION,
    WEEKLY_PAYMENT_DEFINITION,
    build_purchase_package_rows,
    build_snapshot_rows,
    read_ae_csv_artifact,
)
from app.vip.item_catalog import ItemCatalog, load_giftbox_name_overrides


def test_ae_definitions_use_user_account_id_and_previous_seven_days() -> None:
    cumulative_account = CUMULATIVE_PROFILE_DEFINITION["groups"][0]["field"]
    weekly_account = WEEKLY_PAYMENT_DEFINITION["groups"][0]["field"]

    assert cumulative_account == {"name": "#account_id", "type": "user_property"}
    assert weekly_account == {"name": "#account_id", "type": "user_property"}
    assert WEEKLY_PAYMENT_DEFINITION["time_range"] == {
        "mode": "previous",
        "unit": "day",
        "value": 7,
    }
    assert FOURTEEN_DAY_PAYMENT_DEFINITION["time_range"]["value"] == 14
    assert ROLLING_28_DAY_PAYMENT_DEFINITION["time_range"]["value"] == 35
    metric_filter = CUMULATIVE_PROFILE_DEFINITION["metrics"][0]["filters"][0]
    assert metric_filter["field"] == {"name": "is_sandbox", "type": "event_property"}
    assert metric_filter["values"] == ["0"]
    profile_groups = [group["field"]["name"] for group in CUMULATIVE_PROFILE_DEFINITION["groups"]]
    assert profile_groups[-9:] == [
        "build_fp",
        "tech_fp",
        "soldier_fp",
        "beast_fp",
        "hero_fp",
        "hiryu_fp",
        "com_fp",
        "leg_tech_fp",
        "cur_fp",
    ]


def test_build_snapshot_rows_applies_vip_rules_and_deduplicates_by_role_id() -> None:
    cumulative_rows = [
        ["2023-01-01To2026-09-07", "100", "OldName", "1", "S1", "2026-09-01", "(null)", "1500"],
        ["2023-01-01To2026-09-07", "100", "NewName", "11", "S11", "2026-09-08", "CPS-A", "1400"],
        ["2023-01-01To2026-09-07", "101", "Organic", "20", "S20", "2026-09-07", "", "1000"],
        ["2023-01-01To2026-09-07", "102", "Below", "21", "S21", "2026-09-07", "", "999.99"],
    ]
    weekly_rows = [
        ["2026-09-01To2026-09-07", "100", "80"],
        ["2026-09-01To2026-09-07", "100", "80"],
    ]
    fortnight_rows = [
        ["2026-08-25To2026-09-07", "100", "200"],
        ["2026-08-25To2026-09-07", "101", "40"],
    ]
    rolling_28d_rows = [
        ["2026-08-04To2026-09-07", "100", "680"],
        ["2026-08-04To2026-09-07", "101", "400"],
    ]

    rows, cumulative_window, weekly_window, previous_week_window, rolling_28d_window = build_snapshot_rows(
        cumulative_rows,
        weekly_rows,
        fortnight_rows,
        rolling_28d_rows,
    )

    assert cumulative_window == "2023-01-01To2026-09-07"
    assert weekly_window == "2026-09-01To2026-09-07"
    assert previous_week_window == "2026-08-25To2026-09-07（扣除近7日）"
    assert rolling_28d_window == "2026-08-04To2026-09-07（扣除近7日）"
    assert [row["role_id"] for row in rows] == ["100", "101"]
    assert rows[0]["role_name"] == "NewName"
    assert rows[0]["total_payment_amount"] == 1500
    assert rows[0]["payment_7d_amount"] == 80
    assert rows[0]["payment_previous_7d_amount"] == 120
    assert rows[0]["payment_28d_weekly_avg"] == 150
    assert rows[0]["server_type"] == "老服"
    assert rows[0]["user_source"] == "CPS"
    assert rows[1]["server_type"] == "老服"
    assert rows[1]["user_source"] == "自然量"
    assert rows[1]["payment_previous_7d_amount"] == 40
    assert rows[1]["payment_28d_weekly_avg"] == 100


def test_build_snapshot_rows_persists_primary_server_after_merge() -> None:
    cumulative_rows = [
        ["2023-01-01To2026-09-08", "200", "Merged", "S21", "S21", "2026-09-08", "", "1500"]
    ]

    rows, *_ = build_snapshot_rows(cumulative_rows, [])

    assert rows[0]["server_id"] == "19"
    assert rows[0]["server_type"] == "老服"
    assert rows[0]["payment_7d_amount"] == 0
    assert rows[0]["payment_previous_7d_amount"] == 0
    assert rows[0]["payment_28d_weekly_avg"] == 0


def test_build_snapshot_rows_reads_power_fields_from_extended_profile_export() -> None:
    cumulative_rows = [
        [
            "2023-01-01To2026-09-16",
            "200",
            "PowerPlayer",
            "S23",
            "S23",
            "2026-09-16",
            "",
            "100",
            "200",
            "300",
            "400",
            "500",
            "600",
            "700",
            "800",
            "3600",
            "2500",
        ]
    ]

    rows, *_ = build_snapshot_rows(cumulative_rows, [])

    assert rows[0]["build_fp"] == 100
    assert rows[0]["leg_tech_fp"] == 800
    assert rows[0]["cur_fp"] == 3600
    assert rows[0]["total_payment_amount"] == 2500


def test_purchase_packages_do_not_repeat_package_spend_for_each_item() -> None:
    source_rows = [
        ["window", "100", "gift-1", "", "item-1", "", "3", "29.97", "30"],
        ["window", "100", "gift-1", "", "item-2", "建筑加速", "3", "29.97", "60"],
    ]
    catalog = ItemCatalog(
        {"item-1": "高级建筑图纸", "item-2": "建筑加速"},
        {"gift-1": "城建补给"},
        "catalog.xlsx",
    )

    rows, window = build_purchase_package_rows(
        source_rows,
        window_key="lifetime",
        allowed_role_ids={"100"},
        item_catalog=catalog,
    )

    assert window == "window"
    assert len(rows) == 1
    assert rows[0]["payment_amount"] == 29.97
    assert rows[0]["purchase_count"] == 3
    assert rows[0]["category"] == "建筑发展"
    assert "高级建筑图纸" in rows[0]["items_json"]


def test_giftbox_name_overrides_accept_future_manual_mapping(tmp_path: Path) -> None:
    mapping_path = tmp_path / "giftbox_names.json"
    mapping_path.write_text(
        '{"updated_at":"2026-09-17","giftboxes":{"931707":"示例礼包"}}',
        encoding="utf-8",
    )

    assert load_giftbox_name_overrides(mapping_path) == {"931707": "示例礼包"}


def test_missing_payment_aggregate_rows_are_materialized_as_zero() -> None:
    cumulative_rows = [
        ["2023-01-01To2026-09-08", "300", "Dormant", "S1", "S1", "2026-08-10", "", "9000"]
    ]

    rows, *_ = build_snapshot_rows(
        cumulative_rows,
        weekly_rows=[],
        fortnight_rows=[],
        rolling_28d_rows=[],
    )

    assert rows[0]["payment_7d_amount"] == 0
    assert rows[0]["payment_previous_7d_amount"] == 0
    assert rows[0]["payment_28d_weekly_avg"] == 0


def test_read_ae_csv_artifact_handles_gzip_and_repeated_utf8_bom(tmp_path: Path) -> None:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Time", "Account ID", "Amount"])
    writer.writerow(["window", "100", "1234.5"])
    artifact = tmp_path / "data.csv.gz"
    with gzip.open(artifact, "wb") as stream:
        stream.write(b"\xef\xbb\xbf\xef\xbb\xbf" + output.getvalue().encode("utf-8"))

    assert read_ae_csv_artifact(artifact, minimum_columns=3) == [
        ["window", "100", "1234.5"]
    ]


def test_ae_snapshot_repository_replaces_one_project_atomically(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = AEVIPSnapshotRepository(db_path)
    base_row = {
        "role_id": "100",
        "role_name": "Player",
        "server_id": "1",
        "server_name": "S1",
        "last_login_time": "2026-09-08",
        "total_payment_amount": 1500.0,
        "payment_7d_amount": 80.0,
        "payment_previous_7d_amount": 70.0,
        "payment_28d_weekly_avg": 75.0,
        "cps_group": "",
        "server_type": "老服",
        "user_source": "自然量",
        "build_fp": 100.0,
        "tech_fp": 200.0,
        "cur_fp": 300.0,
    }

    repository.replace_snapshot(
        24,
        [base_row, {**base_row, "role_id": "101"}],
        purchase_rows=[
            {
                "role_id": "100",
                "window_key": "lifetime",
                "window_label": "all",
                "giftbox_id": "gift-1",
                "giftbox_name": "城建补给",
                "category": "建筑发展",
                "purchase_count": 2,
                "payment_amount": 19.98,
                "items_json": "[]",
            }
        ],
        started_at="2026-09-08T00:00:00+00:00",
        finished_at="2026-09-08T00:01:00+00:00",
        source_row_count=10,
        cumulative_window="all",
        weekly_window="7d",
    )
    saved_packages = repository.list_purchase_packages(24, "100")
    assert len(saved_packages) == 1
    assert saved_packages[0]["payment_amount"] == 19.98
    repository.replace_snapshot(
        24,
        [{**base_row, "total_payment_amount": 2000.0}],
        started_at="2026-09-08T01:00:00+00:00",
        finished_at="2026-09-08T01:01:00+00:00",
        source_row_count=11,
        cumulative_window="all",
        weekly_window="7d",
    )

    rows = repository.list_snapshot(24)
    latest = repository.get_latest_run(24)
    assert len(rows) == 1
    assert rows[0]["role_id"] == "100"
    assert rows[0]["total_payment_amount"] == 2000.0
    assert rows[0]["payment_previous_7d_amount"] == 70.0
    assert rows[0]["payment_28d_weekly_avg"] == 75.0
    assert rows[0]["build_fp"] == 100.0
    assert repository.list_purchase_packages(24, "100") == []
    assert latest["vip_row_count"] == 1
