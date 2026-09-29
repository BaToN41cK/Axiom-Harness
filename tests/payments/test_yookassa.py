"""YooKassa provider: request shape, response mapping and refusals.

Every test drives the provider through `httpx.MockTransport`, so the real
YooKassa API is never contacted and the suite stays deterministic and offline.
"""

from __future__ import annotations

import json

import httpx
import pytest

from axiom.payments.provider import ProviderPayment, UnavailableProvider
from axiom.payments.service import PaymentService
from axiom.payments.yookassa import YooKassaError, YooKassaProvider, build_provider

SHOP_ID = "1481028"
# A sandbox-shaped key, used only to assert the provider reports test mode.
TEST_KEY = "test_local_sandbox_key_for_unit_tests"
RETURN_URL = "https://axiom.example/return"

PAID_AT = "2026-05-03T10:15:30.123Z"


def _payment_body(
    *,
    status: str = "pending",
    value: str = "300.00",
    currency: str = "RUB",
    order_id: str | None = None,
    paid: bool | None = None,
    captured_at: str | None = None,
    confirmation_url: str | None = "https://yoomoney.ru/api-pages/v2/payment-confirm/epl?orderId=abc",
) -> dict:
    """A YooKassa payment object, shaped like the one in their reference."""
    body: dict = {
        "id": "23d93cac-000f-5000-8000-126628f15141",
        "status": status,
        "paid": paid if paid is not None else status == "succeeded",
        "amount": {"value": value, "currency": currency},
        "created_at": "2026-05-03T10:14:00.000Z",
        "test": True,
    }
    if confirmation_url:
        body["confirmation"] = {"type": "redirect", "confirmation_url": confirmation_url}
    if captured_at:
        body["captured_at"] = captured_at
    if order_id:
        body["metadata"] = {"axiom_order_id": order_id}
    return body


def _provider(handler) -> YooKassaProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return YooKassaProvider(SHOP_ID, TEST_KEY, return_url=RETURN_URL, client=client)


async def test_create_sends_the_documented_request_and_maps_the_reply() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        seen["idempotence"] = request.headers.get("idempotence-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_payment_body(order_id="order-1"))

    payment = await _provider(handler).create("order-1", 30_000)

    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.yookassa.ru/v3/payments"
    # Basic auth with shop id + secret key, per the API reference.
    assert seen["auth"].startswith("Basic ")
    # Idempotence derives from our order id, not from a per-attempt random.
    assert seen["idempotence"] == "axiom-order-1"
    assert seen["body"]["amount"] == {"value": "300.00", "currency": "RUB"}
    assert seen["body"]["capture"] is True
    assert seen["body"]["confirmation"] == {"type": "redirect", "return_url": RETURN_URL}
    assert seen["body"]["metadata"] == {"axiom_order_id": "order-1"}

    assert payment == ProviderPayment(
        order_id="order-1",
        payment_id="23d93cac-000f-5000-8000-126628f15141",
        amount_minor=30_000,
        currency="RUB",
        status="pending",
        payment_url="https://yoomoney.ru/api-pages/v2/payment-confirm/epl?orderId=abc",
        paid_at=None,
    )


async def test_retrying_create_reuses_the_same_idempotence_key() -> None:
    keys: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers.get("idempotence-key"))
        return httpx.Response(200, json=_payment_body(order_id="order-1"))

    provider = _provider(handler)
    await provider.create("order-1", 30_000)
    await provider.create("order-1", 30_000)

    # Two attempts at one order must not be able to charge the payer twice.
    assert keys == ["axiom-order-1", "axiom-order-1"]


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("pending", "pending"),
        # Money is held, not settled: still pending as far as we are concerned.
        ("waiting_for_capture", "pending"),
        ("succeeded", "paid"),
        ("canceled", "cancelled"),
    ],
)
async def test_statuses_map_onto_the_contract(remote: str, expected: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payment_body(status=remote, captured_at=PAID_AT))

    payment = await _provider(handler).status(
        "pay-1", order_id="order-1", amount_minor=30_000, payment_url=None,
    )
    assert payment.status == expected


async def test_settled_payment_carries_the_real_capture_time() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payment_body(status="succeeded", captured_at=PAID_AT))

    payment = await _provider(handler).status(
        "pay-1", order_id="order-1", amount_minor=30_000, payment_url=None,
    )
    assert payment.status == "paid"
    assert payment.paid_at is not None
    assert payment.paid_at > 1_700_000_000



async def test_succeeded_without_paid_flag_is_refused() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_payment_body(status="succeeded", paid=False, captured_at=PAID_AT),
        )

    with pytest.raises(YooKassaError, match="без признака оплаты"):
        await _provider(handler).status(
            "pay-1", order_id="order-1", amount_minor=30_000, payment_url=None,
        )


async def test_unknown_status_and_foreign_currency_are_refused() -> None:
    def unknown(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payment_body(status="something_new"))

    with pytest.raises(YooKassaError, match="Неизвестный статус"):
        await _provider(unknown).create("order-1", 30_000)

    def foreign(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payment_body(currency="USD"))

    with pytest.raises(YooKassaError, match="валюта"):
        await _provider(foreign).create("order-1", 30_000)


async def test_payment_belonging_to_another_order_is_refused() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payment_body(status="succeeded", captured_at=PAID_AT, order_id="someone-else"),
        )

    with pytest.raises(YooKassaError, match="другому заказу"):
        await _provider(handler).status(
            "pay-1", order_id="order-1", amount_minor=30_000, payment_url=None,
        )


async def test_http_errors_become_readable_messages_without_the_key() -> None:
    def unauthorized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"description": "Invalid credentials"})

    with pytest.raises(YooKassaError) as error:
        await _provider(unauthorized).create("order-1", 30_000)
    assert "аутентификацию" in str(error.value)
    # A message shown in the UI must never carry the secret.
    assert TEST_KEY not in str(error.value)


async def test_network_failure_is_not_a_payment_outcome() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(YooKassaError, match="связаться с ЮKassa"):
        await _provider(handler).create("order-1", 30_000)


async def test_sandbox_key_is_reported_as_test_mode() -> None:
    provider = YooKassaProvider(SHOP_ID, TEST_KEY, return_url=RETURN_URL)
    assert provider.test_mode is True
    assert provider.available is True
    live = YooKassaProvider(SHOP_ID, "live_key_value", return_url=RETURN_URL)
    assert live.test_mode is False


async def test_missing_credentials_fail_closed_instead_of_raising(monkeypatch) -> None:
    for name in (
        "AXIOM_YOOKASSA_SHOP_ID",
        "AXIOM_YOOKASSA_SECRET_KEY",
        "AXIOM_YOOKASSA_RETURN_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    provider = build_provider()
    assert isinstance(provider, UnavailableProvider)
    assert provider.available is False


async def test_http_return_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="https"):
        YooKassaProvider(SHOP_ID, TEST_KEY, return_url="http://axiom.example/return")


async def test_service_credits_a_settled_yookassa_payment_exactly_once(tmp_path) -> None:
    state = {"paid": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_payment_body())
        status = "succeeded" if state["paid"] else "pending"
        return httpx.Response(
            200,
            json=_payment_body(status=status, captured_at=PAID_AT if state["paid"] else None),
        )

    service = PaymentService(tmp_path / "payments.db", _provider(handler))
    created = await service.create("user-1", 30_000, "request-1")
    order_id = created["payment"]["id"]
    assert created["payment"]["status"] == "pending"
    assert created["balance_minor"] == 0

    state["paid"] = True
    first = await service.check("user-1", order_id)
    second = await service.check("user-1", order_id)

    assert first["payment"]["status"] == "paid"
    assert first["balance_minor"] == 30_000
    # Polling again must not credit the wallet a second time.
    assert second["balance_minor"] == 30_000

