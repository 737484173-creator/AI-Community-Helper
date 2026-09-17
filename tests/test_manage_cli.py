from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import manage


def test_manage_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "manage.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "AI Community Operation Center manager" in result.stdout
    assert "sync-ae-vip" in result.stdout


def test_dashboard_uses_reliable_source_reload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, *, check):
        captured["command"] = command
        captured["check"] = check

    monkeypatch.setattr(manage.subprocess, "run", fake_run)

    manage._run_dashboard("8510")

    command = captured["command"]
    assert captured["check"] is True
    assert command[command.index("--server.runOnSave") + 1] == "true"
    assert command[command.index("--server.fileWatcherType") + 1] == "poll"


def test_streamlit_config_enables_reliable_source_reload() -> None:
    config = tomllib.loads(Path(".streamlit/config.toml").read_text(encoding="utf-8"))

    assert config["server"]["runOnSave"] is True
    assert config["server"]["fileWatcherType"] == "poll"


def test_dashboard_launch_entrypoints_share_deployment_port() -> None:
    deployment = json.loads(
        Path("deployment/settings.json").read_text(encoding="utf-8")
    )
    port = str(deployment["Port"])
    launcher = Path("scripts/launch_dashboard.py").read_text(encoding="utf-8")
    powershell_launcher = Path("scripts/run_dashboard.ps1").read_text(encoding="utf-8")
    detached_launcher = Path("scripts/run_dashboard_detached.cmd").read_text(
        encoding="utf-8"
    )
    manager = Path("manage.py").read_text(encoding="utf-8")

    assert f'DASHBOARD_PORT = "{port}"' in launcher
    assert f'else {{ "{port}" }}' in powershell_launcher
    assert f"--port {port}" in detached_launcher
    assert f'default="{port}"' in manager
    assert 'ROOT_DIR / ".venv" / "Scripts" / "python.exe"' in launcher
    assert '.venv\\Scripts\\python.exe' in powershell_launcher
    assert '.venv\\Scripts\\python.exe' in detached_launcher
    assert ".cache\\codex-runtimes" not in detached_launcher
    assert '"8510"' not in launcher


def test_manage_init_db_accepts_default_database() -> None:
    result = subprocess.run(
        [sys.executable, "manage.py", "init-db"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Database initialized" in result.stdout


def test_manage_report_daily_with_temp_db(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "report",
            "daily",
            "--db-path",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Generated Daily report" in result.stdout


def test_manage_report_custom_with_temp_db(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "report",
            "custom",
            "--start",
            "2026-07-30 00:00:00",
            "--end",
            "2026-07-31 23:59:59",
            "--db-path",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Generated Custom report" in result.stdout
