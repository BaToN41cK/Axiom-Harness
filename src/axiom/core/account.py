"""AXIOM account client: sign-in, balance, AXIOM PRO and top-ups.

Talks to the same payment backend as the desktop app (``payment-backend``):
password and GitHub/Google OAuth sign-in, ``/v1/me``, PRO subscription and
balance top-ups paid on the YooMoney page. Nothing here invents numbers —
every balance, price and status comes from the server. The session token is
stored locally in ``<AXIOM_HOME>/account.json`` (user-only permissions where
the OS supports it); payment credentials never touch the client.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from axiom.core.config import axiom_home

DEFAULT_BACKEND_URL = "https://axiom-harness.onrender.com"
#: Mirrors payment-backend: PRO is 990 ₽ for 30 days, or $9.90 of AXIOM credits.
PRO_PRICE_RUB_MINOR = 99_000
PRO_PRICE_AXIOM_USD_MINOR = 990
PRO_DAYS = 30
MIN_TOPUP_RUB_MINOR = 10_000
MAX_TOPUP_RUB_MINOR = 10_000_000
#: The backend sleeps when idle; the first request may take up to a minute.
TIMEOUT = httpx.Timeout(60.0, connect=30.0)


class AccountError(Exception):
    """A human-readable failure (server ``detail`` or connection problem)."""


def backend_url() -> str:
    return (os.environ.get("AXIOM_PAYMENT_BACKEND_URL") or DEFAULT_BACKEND_URL).rstrip("/")


def axiom_usd(minor: int | None) -> str:
    minor = int(minor or 0)
    if minor < 0:
        minor = 0
    return f"${minor // 100}.{minor % 100:02d}"


def rubles(minor: int | None) -> str:
    minor = int(minor or 0)
    whole, frac = divmod(minor, 100)
    grouped = f"{whole:,}".replace(",", " ")
    return f"{grouped},{frac:02d} ₽" if frac else f"{grouped} ₽"


def rub_to_axiom_usd_minor(rub_minor: int) -> int:
    """Fixed AXIOM rate: 100 ₽ = $1.00 of internal credits."""
    return max(0, int(rub_minor)) // 100


def parse_amount(value: str) -> int | None:
    """``"300"`` / ``"250,50"`` → kopecks, ``None`` when outside 100…100 000 ₽."""
    value = (value or "").strip().replace(" ", "").replace("₽", "")
    if not re.fullmatch(r"\d{1,6}([.,]\d{1,2})?", value):
        return None
    whole, _, frac = value.replace(",", ".").partition(".")
    amount = int(whole) * 100 + int((frac or "0").ljust(2, "0"))
    return amount if MIN_TOPUP_RUB_MINOR <= amount <= MAX_TOPUP_RUB_MINOR else None


def payment_message(payment: dict | None) -> str:
    if not payment:
        return ""
    status = payment.get("status")
    if status == "paid":
        return "AXIOM PRO activated" if payment.get("type") == "pro" else "Balance updated"
    if status == "expired":
        return "Payment expired"
    if status == "failed":
        reason = payment.get("failure_reason")
        return {
            "below_minimum": "Less than 100 ₽ arrived — balance unchanged, recorded for reconciliation.",
            "late_payment": "Payment arrived after the order expired — contact support.",
            "order_not_pending": "Order already processed — balance not changed twice.",
        }.get(reason or "", "Amount did not match the order — nothing was changed.")
    return "Waiting for payment"


@dataclass
class AccountStore:
    """Local session: bearer token + last known account (for the header)."""

    path: Path | None = None

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = axiom_home() / "account.json"

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # pragma: no cover - Windows ACLs
            pass
        os.replace(tmp, self.path)

    @property
    def token(self) -> str | None:
        token = self._read().get("token")
        return token if isinstance(token, str) and token else None

    def cached_account(self) -> dict[str, Any] | None:
        data = self._read()
        account = data.get("account")
        return account if data.get("token") and isinstance(account, dict) else None

    def save(self, token: str | None = None, account: dict[str, Any] | None = None) -> None:
        data = self._read()
        if token is not None:
            data["token"] = token
        if account is not None:
            data["account"] = account
            data["updated_at"] = time.time()
        self._write(data)

    def clear(self) -> None:
        try:
            self.path.unlink()  # type: ignore[union-attr]
        except OSError:
            pass


class AccountClient:
    """Async client for the AXIOM payment backend."""

    def __init__(self, store: AccountStore | None = None, base_url: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.store = store or AccountStore()
        self.base_url = (base_url or backend_url()).rstrip("/")
        self._transport = transport

    async def _api(self, path: str, *, body: Any = None, token: str | None = None, method: str | None = None) -> Any:
        headers = {"accept": "application/json"}
        if token:
            headers["authorization"] = f"Bearer {token}"
        verb = method or ("GET" if body is None else "POST")
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
                response = await client.request(verb, f"{self.base_url}{path}", json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise AccountError("The account server did not answer in time (it may be waking up) — try again.") from exc
        except httpx.HTTPError as exc:
            raise AccountError(f"Cannot reach the account server: {exc}") from exc
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            if response.status_code == 401 and path == "/v1/me":
                self.store.clear()
            raise AccountError(detail if isinstance(detail, str) else f"Server error {response.status_code}.")
        return data

    def _require_token(self) -> str:
        token = self.store.token
        if not token:
            raise AccountError("Sign in first: /login")
        return token

    def _signed_in(self, data: dict[str, Any]) -> dict[str, Any]:
        self.store.save(token=data["access_token"], account=data["account"])
        return data["account"]

    # ----------------------------------------------------------------- auth

    async def providers(self) -> dict[str, bool]:
        data = await self._api("/v1/auth/providers")
        return {"github": bool(data.get("github")), "google": bool(data.get("google"))}

    async def login(self, username: str, password: str) -> dict[str, Any]:
        return self._signed_in(await self._api("/v1/auth/login", body={"username": username, "password": password}))

    async def register(self, username: str, password: str) -> dict[str, Any]:
        return self._signed_in(await self._api("/v1/auth/register", body={"username": username, "password": password}))

    async def oauth_start(self, provider: str) -> dict[str, str]:
        return await self._api("/v1/auth/oauth/start", body={"provider": provider})

    async def oauth_wait(self, poll_token: str, *, deadline_s: float = 600, interval: float = 2.0,
                         cancelled: Any = None) -> dict[str, Any]:
        """Poll until the browser flow finishes, then redeem the one-time code."""
        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            if cancelled is not None and cancelled():
                raise AccountError("Sign-in cancelled.")
            status = await self._api("/v1/auth/oauth/status", body={"poll_token": poll_token})
            if status.get("status") == "success" and status.get("code"):
                return self._signed_in(await self._api("/v1/auth/oauth/redeem", body={"code": status["code"]}))
            if status.get("status") == "error":
                raise AccountError(status.get("error") or "Sign-in was rejected.")
            await asyncio.sleep(interval)
        raise AccountError("The sign-in link expired — start again.")

    async def logout(self) -> None:
        token = self.store.token
        try:
            if token:
                await self._api("/v1/auth/logout", body={}, token=token)
        finally:
            self.store.clear()

    # -------------------------------------------------------------- account

    async def me(self) -> dict[str, Any]:
        account = await self._api("/v1/me", token=self._require_token())
        self.store.save(account=account)
        return account

    async def buy_pro(self) -> dict[str, Any]:
        data = await self._api("/v1/payments/pro", body={"type": "pro"}, token=self._require_token())
        return data["payment"]

    async def buy_pro_from_balance(self) -> dict[str, Any]:
        data = await self._api("/v1/payments/pro/balance", body={}, token=self._require_token())
        self.store.save(account=data["account"])
        return data["account"]

    async def topup(self, amount_rub_minor: int) -> dict[str, Any]:
        body = {"type": "balance_topup", "amount_rub": f"{amount_rub_minor / 100:.2f}"}
        data = await self._api("/v1/payments/topup", body=body, token=self._require_token())
        return data["payment"]

    async def payment(self, order_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        data = await self._api(f"/v1/payments/{order_id}", token=self._require_token())
        self.store.save(account=data["account"])
        return data["payment"], data["account"]
