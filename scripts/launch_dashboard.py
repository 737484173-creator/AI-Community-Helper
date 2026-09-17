from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
LOCAL_PYTHON = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
LOCAL_PYTHONW = ROOT_DIR / ".venv" / "Scripts" / "pythonw.exe"
PYTHON_EXE = LOCAL_PYTHONW if LOCAL_PYTHONW.exists() else LOCAL_PYTHON
if not PYTHON_EXE.exists():
    PYTHON_EXE = Path(sys.executable).with_name("pythonw.exe")
if not PYTHON_EXE.exists():
    PYTHON_EXE = Path(sys.executable)
LOG_DIR = ROOT_DIR / "logs"
DASHBOARD_PORT = "8502"


def _configured_ae_cli() -> str | None:
    settings_path = ROOT_DIR / "deployment" / "machine-settings.json"
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    candidate = Path(str(payload.get("AeCliPath") or "").strip())
    return str(candidate) if candidate.is_file() else None


def main() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    configured_ae_cli = _configured_ae_cli()
    if configured_ae_cli:
        env["AE_CLI_PATH"] = configured_ae_cli

    stdout = open(LOG_DIR / "dashboard_launcher.out.log", "a", encoding="utf-8")
    stderr = open(LOG_DIR / "dashboard_launcher.err.log", "a", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(PYTHON_EXE),
            "-m",
            "streamlit",
            "run",
            "app/dashboard/streamlit_app.py",
            "--server.port",
            DASHBOARD_PORT,
            "--server.address",
            "127.0.0.1",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=ROOT_DIR,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(
        f"Dashboard launcher started process {process.pid} "
        f"on http://127.0.0.1:{DASHBOARD_PORT}"
    )


if __name__ == "__main__":
    main()
