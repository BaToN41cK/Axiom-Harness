"""YooKassa provider (API v3).

Shape of the integration, and why it is shaped this way:

* **Server only.** The YooKassa quick start states it directly: "Все запросы к
  API ЮKassa необходимо отправлять с вашего сервера." The secret key is the
  full authority over a shop, so it lives in the owner's backend environment —
  never in the Tauri/React client, where any user can read the process memory.
  Credentials are read from the environment and are never written to
  `config.json` or logged.

* **Nothing is trusted from the client.** Amount, status and settlement time
  come from the provider response only. `PaymentService` re-checks that the
  reply matches the stored order before it credits anything.

* **Idempotent.** Every mutating call sends `Idempotence-Key` derived from our
  own order id, so a retry after a timeout re-reads the same YooKassa payment
  instead of creating a second one.

Docs: https://yookassa.ru/developers/api
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from .provider import PaymentStatus, ProviderPayment

API_ROOT = "https://api.yookassa.ru/v3"
#: Only this host may ever receive the secret key.
API_HOST = "api.yookassa.ru"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

#: YooKassa payment status → our status vocabulary.
#: `waiting_for_capture` stays `pending`: the money is held, not settled, and we
#: create payments with `capture=true` so it should not normally appear.
_STATUS_MAP: dict[str, PaymentStatus] = {
    "pending": "pending",
    "waiting_for_capture": "pending",
    "succeeded": "paid",
    "canceled": "cancelled",
}


class YooKassaError(RuntimeError):
    """A provider call failed in a way the caller should surface, not retry."""


def _parse_time(value: object) -> float | None:
    """ISO-8601 from YooKassa → POSIX seconds. None when absent or malformed."""
    if not isinstance(value, str) or not value:
        return None
    try:
        # YooKassa sends a trailing "Z"; fromisoformat needs an explicit offset
        # on Python < 3.11 semantics, so normalise it.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _amount_to_minor(amount: object) -> int | None:
    """`{"value": "300.00", "currency": "RUB"}` → 30000 kopecks."""
    if not isinstance(amount, dict):
        return None
    value = amount.get("value")
    if not isinstance(value, str):
        return None
    try:
        whole, _, fraction = value.partition(".")
        minor = int(whole) * 100 + int((fraction or "0").ljust(2, "0")[:2])
    except ValueError:
        return None
    return minor if minor >= 0 else None


def _minor_to_amount(amount_minor: int) -> str:
    """30000 kopecks → "300.00" (YooKassa requires two decimal places)."""
    return f"{amount_minor // 100}.{amount_minor % 100:02d}"


class YooKassaProvider:
    """Talks to YooKassa API v3 on behalf of the owner's shop.

    `return_url` is where the payer lands after the redirect flow. It has to be
    a page the owner controls: a browser redirect cannot reach the desktop
    client, which is one more reason this provider belongs on a server.
    """

    name = "yookassa"
    automatic_confirmation = True

    def __init__(
        self,
        shop_id: str,
        secret_key: str,
        *,
        return_url: str,
        description: str = "Пополнение баланса AXIOM",
        client: httpx.AsyncClient | None = None,
    ):
        if not shop_id or not secret_key:
            raise ValueError("нужны идентификатор магазина и секретный ключ")
        if not return_url.startswith("https://"):
            raise ValueError("return_url должен быть https-адресом владельца")
        self._shop_id = shop_id
        self._secret = secret_key
        self._return_url = return_url
        self._description = description[:128]
        self._client = client
        self.available = True
        self.message: str | None = None
        #: True for sandbox credentials. Surfaced in the UI so nobody mistakes a
        #: test top-up for a real one.
        self.test_mode = secret_key.startswith("test_")

    @classmethod
    def from_env(cls, client: httpx.AsyncClient | None = None) -> YooKassaProvider:
        """Build from the owner's environment. Secrets never come from config.json."""
        return cls(
            os.environ.get("AXIOM_YOOKASSA_SHOP_ID", "").strip(),
            os.environ.get("AXIOM_YOOKASSA_SECRET_KEY", "").strip(),
            return_url=os.environ.get("AXIOM_YOOKASSA_RETURN_URL", "").strip(),
            description=os.environ.get(
                "AXIOM_YOOKASSA_DESCRIPTION", "Пополнение баланса AXIOM",
            ).strip() or "Пополнение баланса AXIOM",
            client=client,
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotence: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if idempotence:
            headers["Idempotence-Key"] = idempotence
        client = self._client
        owned = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=TIMEOUT)
        try:
            response = await client.request(
                method,
                f"{API_ROOT}{path}",
                json=json,
                headers=headers,
                auth=(self._shop_id, self._secret),
            )
        except httpx.HTTPError as error:
            # A network failure is not a payment outcome: the order keeps its
            # current state and the caller retries with the same key.
            raise YooKassaError(f"Не удалось связаться с ЮKassa: {error}") from error
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            raise YooKassaError(_describe_error(response))
        try:
            payload = response.json()
        except ValueError as error:
            raise YooKassaError("ЮKassa вернула неразбираемый ответ") from error
        if not isinstance(payload, dict):
            raise YooKassaError("ЮKassa вернула ответ неожиданного вида")
        return payload


    def _to_payment(self, payload: dict[str, Any], *, order_id: str) -> ProviderPayment:
        """Map a YooKassa payment object onto our contract, trusting only it."""
        payment_id = payload.get("id")
        if not isinstance(payment_id, str) or not payment_id:
            raise YooKassaError("В ответе ЮKassa нет идентификатора платежа")

        raw_status = payload.get("status")
        status = _STATUS_MAP.get(raw_status) if isinstance(raw_status, str) else None
        if status is None:
            raise YooKassaError(f"Неизвестный статус платежа ЮKassa: {raw_status!r}")

        amount = payload.get("amount")
        amount_minor = _amount_to_minor(amount)
        if amount_minor is None:
            raise YooKassaError("В ответе ЮKassa нет корректной суммы")
        currency = amount.get("currency") if isinstance(amount, dict) else None
        if currency != "RUB":
            raise YooKassaError(f"Неподдерживаемая валюта: {currency!r}")

        confirmation = payload.get("confirmation")
        payment_url = None
        if isinstance(confirmation, dict):
            candidate = confirmation.get("confirmation_url")
            if isinstance(candidate, str) and candidate.startswith("https://"):
                payment_url = candidate

        # `captured_at` is the settlement time. A `succeeded` payment must also
        # carry `paid: true`; PaymentService additionally refuses to credit a
        # paid result that has no timestamp at all.
        paid_at = None
        if status == "paid":
            if payload.get("paid") is not True:
                raise YooKassaError("ЮKassa сообщила succeeded без признака оплаты")
            paid_at = _parse_time(payload.get("captured_at")) or _parse_time(payload.get("created_at"))

        return ProviderPayment(
            order_id=order_id,
            payment_id=payment_id,
            amount_minor=amount_minor,
            currency="RUB",
            status=status,
            payment_url=payment_url,
            paid_at=paid_at,
        )

    @staticmethod
    def _assert_same_order(payload: dict[str, Any], order_id: str) -> None:
        """Refuse to act on a payment that belongs to a different order."""
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            tagged = metadata.get("axiom_order_id")
            if isinstance(tagged, str) and tagged and tagged != order_id:
                raise YooKassaError("Платёж ЮKassa относится к другому заказу")

    async def create(self, order_id: str, amount_minor: int) -> ProviderPayment:
        payload = await self._call(
            "POST",
            "/payments",
            # Idempotence keyed on our own order id: a retry after a timeout
            # returns the existing payment instead of charging twice.
            idempotence=f"axiom-{order_id}",
            json={
                "amount": {"value": _minor_to_amount(amount_minor), "currency": "RUB"},
                "capture": True,
                "confirmation": {"type": "redirect", "return_url": self._return_url},
                "description": self._description,
                # The order id travels with the payment, so a dashboard entry or
                # a webhook can always be traced back to one AXIOM order.
                "metadata": {"axiom_order_id": order_id},
            },
        )
        return self._to_payment(payload, order_id=order_id)

    async def status(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment:
        payload = await self._call("GET", f"/payments/{payment_id}")
        self._assert_same_order(payload, order_id)
        return self._to_payment(payload, order_id=order_id)

    async def cancel(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment:
        payload = await self._call(
            "POST", f"/payments/{payment_id}/cancel", idempotence=f"axiom-cancel-{order_id}",
        )
        self._assert_same_order(payload, order_id)
        return self._to_payment(payload, order_id=order_id)



def _describe_error(response: httpx.Response) -> str:
    """A readable message for the UI that never echoes credentials."""
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("description") or body.get("code") or "")
    except ValueError:
        detail = ""
    if response.status_code == 401:
        return "ЮKassa отклонила аутентификацию: проверьте идентификатор магазина и секретный ключ."
    if response.status_code == 403:
        return "ЮKassa запретила операцию для этого магазина."
    if response.status_code == 404:
        return "Платёж не найден в ЮKassa."
    if response.status_code == 429:
        return "ЮKassa ограничила частоту запросов, попробуйте позже."
    suffix = f": {detail}" if detail else ""
    return f"ЮKassa вернула ошибку {response.status_code}{suffix}"


def build_provider(client: httpx.AsyncClient | None = None):
    """A configured YooKassa provider, or a fail-closed stub when unset.

    Missing credentials are a normal state for a fresh checkout, so this returns
    the unavailable provider with an explanatory message instead of raising.
    """
    from .provider import NOT_CONFIGURED_NOTICE, UnavailableProvider

    try:
        return YooKassaProvider.from_env(client=client)
    except ValueError as error:
        return UnavailableProvider(f"{NOT_CONFIGURED_NOTICE} Причина: {error}.")

