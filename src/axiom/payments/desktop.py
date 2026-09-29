"""Fail-closed desktop adapter, not an authoritative monetary ledger.

The YooKassa secret key is full authority over the shop, and YooKassa itself
requires every API call to originate from the owner's server. The desktop shell
therefore holds no key, performs no provider call and mints no balance: a
user-controlled local process and SQLite file are not a trust boundary.

`axiom.payments.yookassa.YooKassaProvider` + `PaymentService` are the real
integration; they run in the owner's backend, where the credentials live in the
environment. This adapter only reports that state honestly to the UI.
"""

from .provider import DESKTOP_NOTICE, PaymentUnavailable


async def handle_payment(cmd: str, args: dict) -> dict:
    if cmd == "payment_wallet":
        return {
            "balance_minor": 0, "currency": "RUB", "available": False,
            "automatic_confirmation": False, "message": DESKTOP_NOTICE,
            "payment": None,
        }
    if cmd in {"payment_create", "payment_status", "payment_cancel"}:
        raise PaymentUnavailable(DESKTOP_NOTICE)
    raise ValueError("Неизвестная платёжная команда")
