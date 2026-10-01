"""W3.8: portable mode and settings backup/restore."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from axiom.core.config import axiom_home, is_portable
from axiom.core.settings_backup import backup_settings, restore_settings

# ------------------------------------------------------------ portable mode


def test_portable_mode_env_flag(monkeypatch) -> None:
    monkeypatch.delenv("AXIOM_HOME", raising=False)
    monkeypatch.setenv("AXIOM_PORTABLE", "1")
    assert is_portable() is True
    assert axiom_home() == Path.cwd() / ".axiom"


def test_portable_mode_marker(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AXIOM_HOME", raising=False)
    monkeypatch.delenv("AXIOM_PORTABLE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".axiom-portable").write_text("", encoding="utf-8")
    assert is_portable() is True
    assert axiom_home() == tmp_path / ".axiom"


def test_axiom_home_env_overrides_portable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AXIOM_PORTABLE", "1")
    assert axiom_home() == tmp_path / "home"


# ------------------------------------------------------ backup and restore


def test_backup_and_restore_settings(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("AXIOM_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text('{"model": "x"}', encoding="utf-8")
    (home / "providers.json").write_text('{"id": "p"}', encoding="utf-8")

    backup = tmp_path / "backup.zip"
    assert backup_settings(backup) == backup
    assert backup.exists()

    # Corrupt / delete the originals, then restore.
    (home / "config.json").write_text("corrupt", encoding="utf-8")
    (home / "providers.json").unlink()

    restored = restore_settings(backup)
    assert set(restored) == {"config.json", "providers.json"}
    assert json.loads((home / "config.json").read_text(encoding="utf-8")) == {"model": "x"}
    assert json.loads((home / "providers.json").read_text(encoding="utf-8")) == {"id": "p"}


def test_restore_skips_unknown_and_malformed_entries(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("AXIOM_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("config.json", "not json")
        archive.writestr("../evil.txt", "evil")
        archive.writestr("providers.json", '{"ok": true}')

    restored = restore_settings(bad)
    assert restored == ["providers.json"]
    assert not (home / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()
    assert json.loads((home / "providers.json").read_text(encoding="utf-8")) == {"ok": True}
