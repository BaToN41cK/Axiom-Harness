"""Persistent orders and atomic, exactly-once credits.

The caller supplies a *trusted* principal, obtained from server authentication.
The desktop adapter below is intentionally limited to the unavailable provider.
No method accepts a client-supplied status, balance, or paid flag.
"""

import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from .provider import PaymentProvider, PaymentUnavailable, ProviderPayment

MIN_AMOUNT = 10_000
MAX_AMOUNT = 10_000_000


class PaymentService:
    def __init__(self, path: Path, provider: PaymentProvider):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.provider = provider
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS wallets (
                    user_id TEXT PRIMARY KEY, balance_minor INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS payments (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'RUB',
                    provider TEXT NOT NULL, provider_id TEXT UNIQUE, payment_url TEXT,
                    status TEXT NOT NULL, created_at REAL NOT NULL, paid_at REAL,
                    UNIQUE(user_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS credits (
                    payment_id TEXT PRIMARY KEY REFERENCES payments(id),
                    user_id TEXT NOT NULL, amount_minor INTEGER NOT NULL, created_at REAL NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def wallet(self, user_id: str) -> dict:
        with closing(self._connect()) as db:
            row = db.execute("SELECT balance_minor FROM wallets WHERE user_id=?", (user_id,)).fetchone()
            payment = db.execute(
                "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user_id,),
            ).fetchone()
        return {
            "balance_minor": row[0] if row else 0, "currency": "RUB",
            "available": self.provider.available,
            "message": self.provider.message,
            "automatic_confirmation": self.provider.automatic_confirmation,
            "payment": dict(payment) if payment else None,
        }

    def _get(self, user_id: str, order_id: str) -> dict:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM payments WHERE id=? AND user_id=?", (order_id, user_id)).fetchone()
        if row is None:
            raise ValueError("Платёж не найден")
        if row["provider"] != self.provider.name:
            raise ValueError("Провайдер платежа недоступен")
        return dict(row)

    async def create(self, user_id: str, amount_minor: int, request_key: str) -> dict:
        if type(amount_minor) is not int or not MIN_AMOUNT <= amount_minor <= MAX_AMOUNT:
            raise ValueError("Сумма должна быть от 100 до 100 000 ₽")
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
            raise ValueError("Некорректный ключ запроса")
        if not self.provider.available:
            raise PaymentUnavailable(self.provider.message or "Приём платежей не подключён")
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO payments "
                "(id,user_id,request_key,amount_minor,provider,status,created_at) VALUES (?,?,?,?,?,'creating',?)",
                (uuid4().hex, user_id, request_key, amount_minor, self.provider.name, time.time()),
            )
            row = dict(db.execute(
                "SELECT * FROM payments WHERE user_id=? AND request_key=?", (user_id, request_key),
            ).fetchone())
        if row["amount_minor"] != amount_minor:
            raise ValueError("Этот запрос уже связан с другой суммой")
        if row["status"] != "creating":
            return await self.check(user_id, row["id"])
        # Leave creating on timeout: retry the SAME provider order, never mint a new one.
        result = await self.provider.create(row["id"], amount_minor)
        self._apply(row, result)
        return self._response(user_id, row["id"])

    async def check(self, user_id: str, order_id: str, *, cancel: bool = False) -> dict:
        row = self._get(user_id, order_id)
        if row["status"] not in {"paid", "cancelled", "expired", "error"}:
            if row["provider_id"] is None:
                return await self.create(user_id, row["amount_minor"], row["request_key"])
            result = await (
                self.provider.cancel(
                    row["provider_id"], order_id=row["id"], amount_minor=row["amount_minor"],
                    payment_url=row["payment_url"],
                ) if cancel else self.provider.status(
                    row["provider_id"], order_id=row["id"], amount_minor=row["amount_minor"],
                    payment_url=row["payment_url"],
                )
            )
            self._apply(row, result)
        return self._response(user_id, order_id)

    def _response(self, user_id: str, order_id: str) -> dict:
        return {"payment": self._get(user_id, order_id), "balance_minor": self.wallet(user_id)["balance_minor"]}

    def _apply(self, order: dict, result: ProviderPayment) -> None:
        if (result.order_id != order["id"] or result.amount_minor != order["amount_minor"]
                or result.currency != "RUB" or not result.payment_id
                or (order["provider_id"] and result.payment_id != order["provider_id"])):
            raise ValueError("Данные платежа не совпадают с заказом")
        if result.status not in {"pending", "paid", "cancelled", "expired", "error"}:
            raise ValueError("Неизвестный статус платежа")
        if result.status == "paid" and (result.paid_at is None or not math.isfinite(result.paid_at)):
            raise ValueError("Нет подтверждённого времени оплаты")
        url = result.payment_url or order["payment_url"]
        if url:
            parts = urlsplit(url)
            if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                    or len(url.encode("utf-8")) > 271):
                raise ValueError("Некорректная ссылка оплаты")
        if result.status == "pending" and not url:
            raise ValueError("Провайдер не вернул ссылку оплаты")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT status FROM payments WHERE id=?", (order["id"],)).fetchone()[0]
            # A slower poll or cancel reply cannot undo confirmed settlement.
            if current == "paid" or (current in {"cancelled", "expired", "error"} and result.status != "paid"):
                return
            db.execute(
                "UPDATE payments SET provider_id=?,payment_url=?,status=?,paid_at=? WHERE id=?",
                (result.payment_id, url, result.status, result.paid_at, order["id"]),
            )
            if result.status == "paid":
                inserted = db.execute(
                    "INSERT OR IGNORE INTO credits VALUES (?,?,?,?)",
                    (order["id"], order["user_id"], order["amount_minor"], time.time()),
                ).rowcount
                if inserted:
                    db.execute(
                        "INSERT INTO wallets VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET "
                        "balance_minor=balance_minor+excluded.balance_minor",
                        (order["user_id"], order["amount_minor"]),
                    )

