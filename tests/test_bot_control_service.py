from __future__ import annotations

import os

from app.dashboard.bot_control_service import BotControlService
from config.settings import Settings


def _service(tmp_path) -> BotControlService:
    return BotControlService(
        Settings(
            db_path=tmp_path / "community.db",
            discord_bot_token=None,
            discord_proxy=None,
            openai_api_key=None,
            dashboard_password=None,
            log_level="INFO",
        )
    )


def test_pid_exists_detects_current_process(tmp_path) -> None:
    assert _service(tmp_path)._pid_exists(os.getpid()) is True


def test_pid_exists_rejects_unknown_process(tmp_path) -> None:
    assert _service(tmp_path)._pid_exists(4_000_000_000) is False
