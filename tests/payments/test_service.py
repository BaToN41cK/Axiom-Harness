from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from axiom.payments.desktop import handle_payment
from axiom.payments.provider import PaymentUnavailable, ProviderPayment, UnavailableProvider
from axiom.payments.service import PaymentService


@dataclass
class FakeProvider:
    name: str = "fake"
    available: bool = True
    automatic_confirmation: bool = True
    message: str | None = None
    paid: bool = False
    order_id: str = ""

    async def create(self, order_id: str, amount_minor: int) -> ProviderPayment:
        self.order_id = order_id
        return ProviderPayment(order_id, "provider-1", amount_minor, "RUB", "pending", "https://pay.example/order")

    async def status(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment:
        return ProviderPayment(
            order_id, payment_id, amount_minor, "RUB", "paid" if self.paid else "pending",
            payment_url, 1_700_000_000 if self.paid else None,
        )

    async def cancel(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment:
        return ProviderPayment(order_id, payment_id, amount_minor, "RUB", "cancelled", payment_url)


@pytest.mark.asyncio
async def test_paid_payment_is_credited_once(tmp_path: Path) -> None:
    provider = FakeProvider()
    service = PaymentService(tmp_path / "payments.db", provider)
    created = await service.create("user-1", 30_000, "request-1")
    order_id = created["payment"]["id"]

    provider.paid = True
    first = await service.check("user-1", order_id)
    second = await service.check("user-1", order_id)

    assert first["payment"]["status"] == "paid"
    assert first["balance_minor"] == 30_000
    assert second["balance_minor"] == 30_000


@pytest.mark.asyncio
async def test_provider_result_must_match_order(tmp_path: Path) -> None:
    provider = FakeProvider()
    service = PaymentService(tmp_path / "payments.db", provider)
    await service.create("user-1", 30_000, "request-1")

    class WrongAmountProvider(FakeProvider):
        async def create(self, order_id: str, amount_minor: int) -> ProviderPayment:
            return ProviderPayment(order_id, "provider-1", amount_minor + 1, "RUB", "pending", "https://pay.example/order")

    service.provider = WrongAmountProvider()
    with pytest.raises(ValueError, match="не совпадают"):
        await service.create("user-1", 30_000, "request-2")


async def test_disabled_provider_does_not_persist_order(tmp_path: Path) -> None:
    service = PaymentService(tmp_path / "payments.db", UnavailableProvider())
    with pytest.raises(PaymentUnavailable):
        await service.create("user-1", 30_000, "request-1")
    assert service.wallet("user-1")["payment"] is None
    assert service.wallet("user-1")["balance_minor"] == 0


async def test_client_claims_and_env_cannot_enable_desktop_payments(monkeypatch) -> None:
    # Even with credentials present in the local environment, the desktop shell
    # must not create payments: the key belongs to the owner's server only.
    monkeypatch.setenv("AXIOM_YOOKASSA_SHOP_ID", "1481028")
    monkeypatch.setenv("AXIOM_YOOKASSA_SECRET_KEY", "test_client_controlled_value")
    monkeypatch.setenv("AXIOM_YOOKASSA_RETURN_URL", "https://example.org/return")
    monkeypatch.setenv("AXIOM_PAYMENT_ADMIN_TOKEN", "client-controlled")
    claims = {"user_id": "owner", "paid": True, "balance_minor": 999999, "amount_minor": 30000}
    wallet = await handle_payment("payment_wallet", claims)
    assert wallet["available"] is False
    assert wallet["automatic_confirmation"] is False
    assert wallet["payment"] is None
    assert wallet["balance_minor"] == 0
    for command in ("payment_create", "payment_status", "payment_cancel"):
        with pytest.raises(PaymentUnavailable):
            await handle_payment(command, claims)
    for command in ("payment_confirm", "payment_admin"):
        with pytest.raises(ValueError):
            await handle_payment(command, claims)


async def test_another_user_cannot_check_or_cancel_payment(tmp_path: Path) -> None:
    service = PaymentService(tmp_path / "payments.db", FakeProvider())
    created = await service.create("owner", 30000, "request-1")
    for cancel in (False, True):
        with pytest.raises(ValueError, match="не найден"):
            await service.check("other", created["payment"]["id"], cancel=cancel)



