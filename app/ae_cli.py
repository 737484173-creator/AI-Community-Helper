from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


MACHINE_SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "deployment" / "machine-settings.json"
)


def resolve_ae_cli(executable: str = "ae-cli") -> str | None:
    """Resolve AE CLI even when a background Windows process has a minimal PATH."""
    configured_path = os.getenv("AE_CLI_PATH", "").strip()
    if configured_path:
        resolved = _existing_file(Path(configured_path))
        if resolved:
            return resolved

    resolved = shutil.which(executable)
    if resolved:
        return resolved

    requested_path = Path(executable)
    if requested_path.is_absolute() or requested_path.parent != Path("."):
        resolved = _existing_file(requested_path)
        if resolved:
            return resolved

    for npm_directory in _windows_npm_directories():
        for filename in _windows_command_names(requested_path.name):
            resolved = _existing_file(npm_directory / filename)
            if resolved:
                return resolved

    resolved = _machine_configured_cli()
    if resolved:
        return resolved
    return None


def _machine_configured_cli() -> str | None:
    try:
        payload = json.loads(MACHINE_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    configured_path = str(payload.get("AeCliPath") or "").strip()
    return _existing_file(Path(configured_path)) if configured_path else None


def _windows_npm_directories() -> tuple[Path, ...]:
    candidates: list[Path] = []
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "npm")

    user_profile = os.getenv("USERPROFILE", "").strip()
    if user_profile:
        candidates.append(Path(user_profile) / "AppData" / "Roaming" / "npm")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def _windows_command_names(name: str) -> tuple[str, ...]:
    if Path(name).suffix:
        return (name,)
    return (f"{name}.cmd", f"{name}.exe", f"{name}.bat", name)


def _existing_file(path: Path) -> str | None:
    try:
        if path.is_file():
            return str(path.resolve())
    except OSError:
        return None
    return None
