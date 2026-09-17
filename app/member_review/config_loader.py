from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.settings import BASE_DIR


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_server_mapping() -> dict[str, str]:
    data = _load_json(BASE_DIR / "config" / "server_mapping.json", {})
    return {str(key): str(value) for key, value in data.items()}


def load_review_messages() -> dict[str, str]:
    return dict(_load_json(BASE_DIR / "config" / "member_review_messages.json", {}))


def load_review_rules() -> dict[str, Any]:
    return dict(
        _load_json(
            BASE_DIR / "config" / "member_review_rules.json",
            {"mode": "manual_confirmation", "auto_approve_enabled": False},
        )
    )
