import base64
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import main
import pytest
from axiom_payments import Settings, iso, utc_now


@pytest.fixture
def app(tmp_path):
    return main.create_app(
        Settings(
            database_path=str(tmp_path / "auth.sqlite3"),
            wallet_id="",
            notification_secret="",
            public_url="https://testserver",
            commercial_use_approved=False,
            allowed_origins=(),
            github_client_id="github-id",
            github_client_secret="github-secret",
            google_client_id="google-id",
            google_client_secret="google-secret",
        )
    )


async def start_flow(desktop, browser, provider):
    start = await desktop.post("/v1/auth/oauth/start", json={"provider": provider})
    assert start.status_code == 200
    assert not desktop.cookies
    payload = start.json()
    redirect = await browser.get(payload["authorization_url"])
    assert redirect.status_code == 303
    assert "HttpOnly" in redirect.headers["set-cookie"]
    assert "Secure" in redirect.headers["set-cookie"]
    query = parse_qs(urlsplit(redirect.headers["location"]).query)
    return payload, query


class ProviderResponse:
    def __init__(self, value):
        self.value = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.value[:size]


@pytest.mark.parametrize("provider", ["github", "google"])
async def test_provider_flow_isolated_browser_pkce_and_replay(app, monkeypatch, provider):
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as desktop,
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as browser,
    ):
        payload, query = await start_flow(desktop, browser, provider)
        state = query["state"][0]
        callback = f"/v1/auth/oauth/{provider}/callback"
        assert payload["poll_token"] != state
        # Browser-visible state cannot retrieve a session.
        assert (await desktop.post("/v1/auth/oauth/status", json={"poll_token": state})).status_code == 401
        # No cookie in the application or another browser.
        assert (await desktop.get(callback, params={"state": state, "code": "stolen"})).status_code == 400
        calls = []

        def provider_request(request, timeout):
            calls.append(request.full_url)
            assert timeout == 15
            if request.data:
                form = parse_qs(request.data.decode())
                verifier = form["code_verifier"][0]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                assert query["code_challenge"] == [challenge]
                assert form["redirect_uri"] == query["redirect_uri"]
                assert form["client_secret"] == [f"{provider}-secret"]
                return ProviderResponse({"access_token": "provider-token"})
            assert request.get_header("Authorization") == "Bearer provider-token"
            if provider == "github":
                if request.full_url.endswith("/user/emails"):
                    return ProviderResponse([{"email": "octo@example.test", "primary": True, "verified": True}])
                return ProviderResponse({"id": 123, "login": "octocat", "email": None})
            return ProviderResponse(
                {"sub": "google-sub", "name": "Octo Cat", "email": "a@example.test", "email_verified": True}
            )

        monkeypatch.setattr(main, "urlopen", provider_request)
        result = await browser.get(callback, params={"state": state, "code": "provider-code"})
        assert result.status_code == 200
        assert result.headers["Cache-Control"] == "no-store"
        assert result.headers["Referrer-Policy"] == "no-referrer"
        assert "provider-token" not in result.text
        assert not browser.cookies
        assert (await browser.get(callback, params={"state": state, "code": "provider-code"})).status_code == 400
        assert len(calls) == (3 if provider == "github" else 2)
        with closing(app.state.store._connect()) as db:
            assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        poll = await desktop.post("/v1/auth/oauth/status", json={"poll_token": payload["poll_token"]})
        assert poll.json()["status"] == "success"
        code = poll.json()["code"]
        session = await desktop.post("/v1/auth/oauth/redeem", json={"code": code})
        assert session.status_code == 200
        token = session.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert (await desktop.get("/v1/me", headers=headers)).status_code == 200
        assert (await desktop.post("/v1/auth/oauth/redeem", json={"code": code})).status_code == 401
        assert (await desktop.post("/v1/auth/logout", headers=headers)).status_code == 204
        assert (await desktop.get("/v1/me", headers=headers)).status_code == 401


@pytest.mark.parametrize("outcome", ["cancel", "error", "expired", "invalid-profile"])
async def test_failed_oauth_never_issues_session(app, monkeypatch, outcome):
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as desktop,
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as browser,
    ):
        payload, query = await start_flow(desktop, browser, "google")
        if outcome == "expired":
            with closing(app.state.store._connect()) as db:
                db.execute("UPDATE oauth_flows SET expires_at = ?", (iso(utc_now() - timedelta(seconds=1)),))

        def fail(request, timeout):
            if outcome == "invalid-profile":
                return ProviderResponse({"access_token": "token"}) if request.data else ProviderResponse({"sub": {}})
            raise OSError("provider network error")

        monkeypatch.setattr(main, "urlopen", fail)
        params = {"state": query["state"][0]}
        params.update({"error": "access_denied"} if outcome == "cancel" else {"code": "code"})
        await browser.get("/v1/auth/oauth/google/callback", params=params)
        poll = await desktop.post("/v1/auth/oauth/status", json={"poll_token": payload["poll_token"]})
        assert poll.json()["status"] == "error"
        with closing(app.state.store._connect()) as db:
            assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_identity_stable_no_username_email_merge_and_code_expiry(app):
    store = app.state.store
    local, _ = store.register("octocat", "a-long-test-password")
    user = store.oauth_login("github", "1", "octocat", "same@example.test", None)
    again = store.oauth_login("github", "1", "newname", None, None)
    other = store.oauth_login("google", "1", "octocat", "same@example.test", None)
    assert user == again
    # Provider subjects remain the only automatic account key. Email matching
    # must not silently merge identities or a password account.
    assert len({local, user, other}) == 3
    code = store.create_oauth_code(user)
    with closing(store._connect()) as db:
        db.execute("UPDATE oauth_codes SET expires_at = ?", (iso(utc_now() - timedelta(seconds=1)),))
    assert store.redeem_oauth_code(code) is None
    assert store.redeem_oauth_code("тест") is None
    with pytest.raises(ValueError, match="invalid_credentials"):
        store.login("octocat-1", "a-long-test-password")


async def test_local_registration_login_validation_logout(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        body = {"username": "alice", "password": "correct-long-password"}
        assert (await client.post("/v1/auth/register", json={**body, "password": "short"})).status_code == 422
        first = await client.post("/v1/auth/register", json=body)
        assert first.status_code == 200
        assert (await client.post("/v1/auth/register", json=body)).status_code == 409
        assert (
            await client.post("/v1/auth/login", json={**body, "password": "incorrect-long-password"})
        ).status_code == 401
        login = await client.post("/v1/auth/login", json={**body, "username": "ALICE"})
        assert login.json()["account"]["id"] == first.json()["account"]["id"]
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert (await client.post("/v1/auth/logout", headers=headers)).status_code == 204
        assert (await client.get("/v1/me", headers=headers)).status_code == 401
        with sqlite3.connect(app.state.settings.database_path) as db:
            assert db.execute("SELECT password_hash FROM users").fetchone()[0] != body["password"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "redirect_uri", "endpoint"),
    [
        ("google", "https://testserver/auth/google/callback", "/auth/google"),
        ("github", "https://testserver/auth/github/callback", "/auth/github"),
    ],
)
async def test_provider_compatibility_entrypoints_use_configured_callbacks(app, provider, redirect_uri, endpoint):
    settings = replace(
        app.state.settings,
        google_redirect_uri="https://testserver/auth/google/callback",
        github_redirect_uri="https://testserver/auth/github/callback",
    )
    compatible = main.create_app(replace(settings, database_path=app.state.settings.database_path + "-compat"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=compatible), base_url="https://testserver"
    ) as client:
        response = await client.get(endpoint, follow_redirects=False)
        assert response.status_code == 303
        location = response.headers["location"]
        query = parse_qs(urlsplit(location).query)
        assert query["redirect_uri"] == [redirect_uri]
        assert query["state"]
        assert "client_secret" not in location
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie


@pytest.mark.asyncio
async def test_compatibility_callback_rejects_invalid_state(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/auth/google/callback", params={"state": "not-a-real-state", "code": "code"})
        assert response.status_code == 400
        assert "Ссылка входа истекла" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["github", "google"])
async def test_configured_callback_finishes_desktop_login(app, monkeypatch, provider):
    settings = replace(
        app.state.settings,
        google_redirect_uri="https://testserver/auth/google/callback",
        github_redirect_uri="https://testserver/auth/github/callback",
    )
    compatible = main.create_app(replace(settings, database_path=app.state.settings.database_path + "-new"))

    def provider_request(request, timeout):
        assert timeout == 15
        if request.data:
            assert parse_qs(request.data.decode())["redirect_uri"] == [settings.oauth_redirect_uri(provider)]
            return ProviderResponse({"access_token": "test-provider-token"})
        if request.full_url.endswith("/user/emails"):
            return ProviderResponse([{"email": "user@example.test", "verified": True, "primary": True}])
        if provider == "github":
            return ProviderResponse({"id": 123, "login": "github-user", "email": None})
        return ProviderResponse({"sub": "google-user", "email": "user@example.test", "email_verified": True})

    monkeypatch.setattr(main, "urlopen", provider_request)
    transport = httpx.ASGITransport(app=compatible)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as desktop,
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as browser,
    ):
        start = await desktop.post("/v1/auth/oauth/start", json={"provider": provider})
        assert start.status_code == 200
        assert urlsplit(start.json()["authorization_url"]).path == f"/auth/{provider}"
        redirect = await browser.get(start.json()["authorization_url"])
        assert redirect.status_code == 303
        state = parse_qs(urlsplit(redirect.headers["location"]).query)["state"][0]
        callback = f"/auth/{provider}/callback"
        assert (await desktop.get(callback, params={"state": state, "code": "code"})).status_code == 400
        completed = await browser.get(callback, params={"state": state, "code": "code"})
        assert completed.status_code == 200
        assert not browser.cookies
        result = await desktop.post("/v1/auth/oauth/status", json={"poll_token": start.json()["poll_token"]})
        token_response = await desktop.post("/v1/auth/oauth/redeem", json={"code": result.json()["code"]})
        headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}
        account = await desktop.get("/auth/me", headers=headers)
        assert account.status_code == 200
        assert (await desktop.post("/auth/logout", headers=headers)).status_code == 204
        assert (await desktop.get("/auth/me", headers=headers)).status_code == 401
