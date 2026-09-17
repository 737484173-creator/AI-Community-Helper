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
    build_snapshot_rows,
    read_ae_csv_artifact,
)


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
    }

    repository.replace_snapshot(
        24,
        [base_row, {**base_row, "role_id": "101"}],
        started_at="2026-09-08T00:00:00+00:00",
        finished_at="2026-09-08T00:01:00+00:00",
        source_row_count=10,
        cumulative_window="all",
        weekly_window="7d",
    )
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
    assert latest["vip_row_count"] == 1
