from __future__ import annotations

from app.dashboard.auth import verify_password


def test_dashboard_auth_allows_development_mode_without_password() -> None:
    result = verify_password("", None)

    assert result.allowed is True
    assert result.development_mode is True


def test_dashboard_auth_accepts_matching_password() -> None:
    result = verify_password("secret", "secret")

    assert result.allowed is True
    assert result.development_mode is False


def test_dashboard_auth_rejects_wrong_password() -> None:
    result = verify_password("wrong", "secret")

    assert result.allowed is False
    assert result.development_mode is False

