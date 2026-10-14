from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
COMMON_SCRIPT = ROOT_DIR / "deployment" / "common.ps1"
RUNNER_SCRIPT = ROOT_DIR / "deployment" / "run-aidc.ps1"


def _ps_quote(value: Path) -> str:
    return str(value).replace("'", "''")


def _remove_pid_file(path: Path, expected_process_id: int | None = None) -> str:
    expected = (
        f" -ExpectedProcessId {expected_process_id}"
        if expected_process_id is not None
        else ""
    )
    script = (
        f". '{_ps_quote(COMMON_SCRIPT)}'; "
        f"Remove-AidcPidFileSafely -Path '{_ps_quote(path)}'{expected}"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _write_pid_file(path: Path, process_id: int) -> None:
    script = (
        f". '{_ps_quote(COMMON_SCRIPT)}'; "
        f"Write-AidcPidFileSafely -Path '{_ps_quote(path)}' "
        f"-Record @{{ ProcessId = {process_id}; Port = 8502 }}"
    )
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_pid_cleanup_is_idempotent_when_file_is_already_missing(tmp_path: Path) -> None:
    pid_file = tmp_path / "missing.pid.json"

    assert _remove_pid_file(pid_file, expected_process_id=1234) == "True"


def test_pid_record_is_published_as_complete_json(tmp_path: Path) -> None:
    pid_file = tmp_path / "aidc-dashboard.pid.json"

    _write_pid_file(pid_file, process_id=1234)

    assert json.loads(pid_file.read_text(encoding="utf-8-sig")) == {
        "ProcessId": 1234,
        "Port": 8502,
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_pid_cleanup_removes_file_owned_by_expected_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "owned.pid.json"
    pid_file.write_text(json.dumps({"ProcessId": 1234}), encoding="utf-8")

    assert _remove_pid_file(pid_file, expected_process_id=1234) == "True"
    assert not pid_file.exists()


def test_pid_cleanup_preserves_file_when_ownership_changed(tmp_path: Path) -> None:
    pid_file = tmp_path / "new-owner.pid.json"
    pid_file.write_text(json.dumps({"ProcessId": 5678}), encoding="utf-8")

    assert _remove_pid_file(pid_file, expected_process_id=1234) == "False"
    assert pid_file.exists()


def test_supervisor_tracks_streamlit_process_directly() -> None:
    script = RUNNER_SCRIPT.read_text(encoding="utf-8")

    assert '"manage.py"' not in script
    assert '"streamlit"' in script
    assert '"app/dashboard/streamlit_app.py"' in script
    assert "Write-AidcPidFileSafely" in script
    assert 'throw "AIDC is already healthy' not in script
