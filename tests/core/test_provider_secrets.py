"""OS-protected provider secret storage (release-security audit, P0).

`providers.json` must never hold a usable plaintext key on Windows (DPAPI
user-scope blob instead), and `status_rows()` / the bridge must never echo
key material back to any frontend.
"""

from __future__ import annotations

import json
import sys

import pytest

from axiom.core.providers.manager import ProviderManager
from axiom.core.secrets import (
    DPAPI_PREFIX,
    SecretsError,
    is_protected,
    protect,
    unprotect,
)


def test_protect_empty_stays_empty() -> None:
    assert protect("") == ""
    assert unprotect("") == ""


def test_protect_unprotect_round_trip() -> None:
    stored = protect("sk-live-456")
    assert stored != "sk-live-456"
    assert is_protected(stored)
    assert unprotect(stored) == "sk-live-456"


def test_unprotect_legacy_plaintext_passes_through() -> None:
    assert unprotect("sk-old-plaintext") == "sk-old-plaintext"


def test_unprotect_corrupt_blob_fails_closed() -> None:
    with pytest.raises(SecretsError):
        unprotect(DPAPI_PREFIX + "!!!not-base64!!!")
    with pytest.raises(SecretsError):
        unprotect(DPAPI_PREFIX + "aGk=")  # valid base64, not a DPAPI blob


def test_manager_never_writes_plaintext_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    mgr = ProviderManager()
    mgr.set_key("openai", "sk-test-789")
    raw = (tmp_path / "providers.json").read_text(encoding="utf-8")
    if sys.platform == "win32":
        assert "sk-test-789" not in raw
        assert is_protected(json.loads(raw)["openai"]["api_key"])
    # A fresh manager recovers the working key on every platform.
    assert ProviderManager()._configs["openai"].api_key == "sk-test-789"


def test_manager_loads_legacy_plaintext_and_migrates_on_save(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    (tmp_path / "providers.json").write_text(
        json.dumps(
            {"xai": {"id": "xai", "api_key": "sk-legacy", "base_url": "", "enabled": True, "status": "not_configured"}}
        ),
        encoding="utf-8",
    )
    mgr = ProviderManager()
    assert mgr.has_key("xai") is True
    assert mgr._configs["xai"].api_key == "sk-legacy"
    mgr.save()
    raw = (tmp_path / "providers.json").read_text(encoding="utf-8")
    if sys.platform == "win32":
        assert "sk-legacy" not in raw
    assert ProviderManager()._configs["xai"].api_key == "sk-legacy"


def test_manager_treats_corrupt_blob_as_missing_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    (tmp_path / "providers.json").write_text(
        json.dumps(
            {
                "xai": {
                    "id": "xai",
                    "api_key": DPAPI_PREFIX + "aGk=",
                    "base_url": "",
                    "enabled": True,
                    "status": "not_configured",
                }
            }
        ),
        encoding="utf-8",
    )
    mgr = ProviderManager()
    assert mgr._configs["xai"].api_key == ""


def test_status_rows_contain_no_key_material(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_HOME", str(tmp_path))
    mgr = ProviderManager()
    mgr.set_key("anthropic", "sk-ant-secret")
    dumped = json.dumps(mgr.status_rows(), ensure_ascii=False)
    assert "sk-ant-secret" not in dumped
    assert "api_key" not in dumped
