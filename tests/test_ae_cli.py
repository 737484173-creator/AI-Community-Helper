from __future__ import annotations

from pathlib import Path
import json

import app.ae_cli as ae_cli


def test_resolve_ae_cli_uses_explicit_configuration(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "configured-ae-cli.cmd"
    executable.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("AE_CLI_PATH", str(executable))
    monkeypatch.setattr(ae_cli.shutil, "which", lambda _name: None)

    assert ae_cli.resolve_ae_cli() == str(executable.resolve())


def test_resolve_ae_cli_falls_back_to_windows_npm_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    appdata = tmp_path / "Roaming"
    executable = appdata / "npm" / "ae-cli.cmd"
    executable.parent.mkdir(parents=True)
    executable.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.delenv("AE_CLI_PATH", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    monkeypatch.setattr(ae_cli.shutil, "which", lambda _name: None)

    assert ae_cli.resolve_ae_cli() == str(executable.resolve())


def test_resolve_ae_cli_uses_machine_deployment_setting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "npm" / "ae-cli.cmd"
    executable.parent.mkdir(parents=True)
    executable.write_text("@echo off\n", encoding="utf-8")
    settings_path = tmp_path / "machine-settings.json"
    settings_path.write_text(
        json.dumps({"AeCliPath": str(executable)}),
        encoding="utf-8",
    )
    monkeypatch.delenv("AE_CLI_PATH", raising=False)
    monkeypatch.setattr(ae_cli, "MACHINE_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(ae_cli.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ae_cli, "_windows_npm_directories", lambda: ())

    assert ae_cli.resolve_ae_cli() == str(executable.resolve())
