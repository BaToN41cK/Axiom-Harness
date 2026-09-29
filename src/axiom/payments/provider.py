"""Provider-neutral payments contract. Amounts are integer kopecks throughout."""

from dataclasses import dataclass
from typing import Literal, Protocol

PaymentStatus = Literal["creating", "pending", "paid", "cancelled", "expired", "error"]

NOT_CONFIGURED_NOTICE = (
    "Приём платежей не настроен. Нужны идентификатор магазина и секретный ключ "
    "ЮKassa на доверенном сервере владельца — в локальном приложении их держать нельзя."
)

DESKTOP_NOTICE = (
    "Пополнение выполняется на сервере владельца AXIOM. Локальное приложение не "
    "хранит платёжный ключ и не подтверждает оплату самостоятельно."
)


class PaymentUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderPayment:
    order_id: str
    payment_id: str
    amount_minor: int
    currency: str
    status: PaymentStatus
    payment_url: str | None = None
    paid_at: float | None = None


class PaymentProvider(Protocol):
    name: str
    available: bool
    automatic_confirmation: bool
    message: str | None

    async def create(self, order_id: str, amount_minor: int) -> ProviderPayment: ...

    async def status(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment: ...

    async def cancel(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment: ...


class UnavailableProvider:
    """Fail closed when no trusted provider credentials are configured.

    Used by the desktop adapter and by any deployment that was not given a shop
    id and secret key. It never invents a payment URL and never reports a
    payment as settled.
    """

    name = "unavailable"
    available = False
    automatic_confirmation = False

    def __init__(self, message: str = NOT_CONFIGURED_NOTICE):
        self.message = message

    async def create(self, order_id: str, amount_minor: int) -> ProviderPayment:
        raise PaymentUnavailable(self.message)

    async def status(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment:
        raise PaymentUnavailable("Проверка оплаты недоступна: провайдер не настроен.")

    async def cancel(
        self, payment_id: str, *, order_id: str, amount_minor: int, payment_url: str | None,
    ) -> ProviderPayment:
        raise PaymentUnavailable("Отмена недоступна: провайдер не настроен.")
