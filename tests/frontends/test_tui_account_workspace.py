"""TUI: folder choice drives the side panel; account client talks to the backend."""

from __future__ import annotations

import httpx
import pytest

from axiom.core.account import AccountClient, AccountError, AccountStore, parse_amount, rub_to_axiom_usd_minor
from axiom.frontends.tui.widgets.folder_picker import resolve_folder

ACCOUNT = {"id": "u1", "username": "neo", "balance_minor": 990, "pro_active": False,
           "pro_activated_at": None, "pro_expires_at": None, "payments_available": True,
           "payments_message": None, "latest_payment": None}


def _client(tmp_path, handler) -> AccountClient:
    return AccountClient(store=AccountStore(tmp_path / "account.json"), base_url="https://x.test",
                         transport=httpx.MockTransport(handler))


def test_parse_amount_limits() -> None:
    assert parse_amount("300") == 30_000
    assert parse_amount("250,50") == 25_050
    assert parse_amount("99") is None
    assert parse_amount("100001") is None
    assert rub_to_axiom_usd_minor(30_000) == 300


async def test_login_persists_token_and_account(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/login":
            return httpx.Response(200, json={"access_token": "tok", "account": ACCOUNT})
        if request.url.path == "/v1/me":
            assert request.headers["authorization"] == "Bearer tok"
            return httpx.Response(200, json=ACCOUNT)
        return httpx.Response(404)

    client = _client(tmp_path, handler)
    account = await client.login("neo", "password1")
    assert account["username"] == "neo"
    assert client.store.token == "tok"
    assert (await client.me())["balance_minor"] == 990


async def test_server_detail_is_surfaced(tmp_path) -> None:
    client = _client(tmp_path, lambda r: httpx.Response(401, json={"detail": "Неверное имя пользователя или пароль."}))
    with pytest.raises(AccountError, match="Неверное"):
        await client.login("neo", "bad-pass")


async def test_expired_session_is_cleared(tmp_path) -> None:
    client = _client(tmp_path, lambda r: httpx.Response(401, json={"detail": "expired"}))
    client.store.save(token="old", account=ACCOUNT)
    with pytest.raises(AccountError):
        await client.me()
    assert client.store.token is None


def test_resolve_folder(tmp_path) -> None:
    (tmp_path / "proj").mkdir()
    (tmp_path / "file.txt").write_text("x")
    assert resolve_folder("proj", tmp_path) == (tmp_path / "proj").resolve()
    assert resolve_folder(str(tmp_path / "file.txt")) is None
    assert resolve_folder("") is None


async def test_folder_picker_tolerates_duplicate_places(tmp_path, monkeypatch) -> None:
    """Home == launch folder and repeated recents must not crash (DuplicateID)."""
    from pathlib import Path

    from textual.app import App

    from axiom.frontends.tui.widgets.folder_picker import FolderPicker, useful_recent

    home = tmp_path / "home"
    (home / "proj").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(home)
    recent = [str(home), str(home / "proj"), str(home / "proj")]

    class _Harness(App):
        def on_mount(self) -> None:
            self.push_screen(FolderPicker(None, recent))

    app = _Harness()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, FolderPicker)
        assert len(set(app.screen._place_paths.values())) == len(app.screen._place_paths)


def test_useful_recent_skips_temp_and_duplicates(tmp_path) -> None:
    import tempfile
    from pathlib import Path

    from axiom.frontends.tui.widgets.folder_picker import useful_recent

    temp_dir = Path(tempfile.mkdtemp())
    assert useful_recent([str(temp_dir), str(temp_dir)]) == []
