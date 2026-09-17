from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience dependency
    load_dotenv = None


def _load_env_file(path: Path) -> None:
    if load_dotenv:
        load_dotenv(path)
        return

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    db_path: Path
    discord_bot_token: str | None
    discord_proxy: str | None
    openai_api_key: str | None
    dashboard_password: str | None
    log_level: str
    discord_auto_backfill_hours: int = 24


def _non_negative_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def get_settings() -> Settings:
    _load_env_file(BASE_DIR / ".env")

    db_path = Path(os.getenv("COMMUNITY_DB_PATH", BASE_DIR / "data" / "community.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    return Settings(
        db_path=db_path,
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN"),
        discord_proxy=os.getenv("DISCORD_PROXY") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        dashboard_password=os.getenv("DASHBOARD_PASSWORD"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        discord_auto_backfill_hours=_non_negative_int_env(
            "DISCORD_AUTO_BACKFILL_HOURS",
            24,
        ),
    )
