from __future__ import annotations

from config.settings import get_settings


def test_settings_reads_dashboard_password(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")

    settings = get_settings()

    assert settings.dashboard_password == "secret"


def test_settings_reads_discord_auto_backfill_hours(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_AUTO_BACKFILL_HOURS", "48")

    settings = get_settings()

    assert settings.discord_auto_backfill_hours == 48
