"""Small, server-side payment and account store for the AXIOM desktop app."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import string
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

RUB = Decimal("0.01")
PRO_PRICE_MINOR = 99_000
PRO_DAYS = 30
MIN_TOPUP_MINOR = 10_000
MAX_TOPUP_MINOR = 10_000_000
TOKEN_TTL_DAYS = 30
ORDER_TTL_HOURS = 24
PASSWORD_ITERATIONS = 310_000
YOOMONEY_NOTIFICATION_SECRET_FILE = Path("/etc/secrets/YOOMONEY_NOTIFICATION_SECRET")


def load_yoomoney_notification_secret() -> str:
    """Load the notification secret from the environment or a Render Secret File."""
    env_value = os.getenv("YOOMONEY_NOTIFICATION_SECRET", "").strip()
    if env_value:
        return env_value

    try:
        return YOOMONEY_NOTIFICATION_SECRET_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def rubles_to_minor(value: str | Decimal) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid_amount") from exc
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(RUB):
        raise ValueError("invalid_amount")
    return int(amount * 100)


def minor_to_rubles(value: int) -> str:
    return f"{Decimal(value) / 100:.2f}"


def _rounded_minor(value: Decimal) -> int:
    return int((value / RUB).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gross_up_for_wallet(credit_minor: int) -> int:
    """Find the PC button amount whose documented 1% fee nets the requested sum."""
    target = Decimal(credit_minor) / 100
    # YooMoney's PC button formula is amount_due = sum - sum * (a / (1 + a)), a=.01.
    center = _rounded_minor(target * Decimal("1.01"))
    for gross_minor in range(max(1, center - 5), center + 6):
        gross = Decimal(gross_minor) / 100
        fee_minor = _rounded_minor(gross / Decimal(101))
        if gross_minor - fee_minor == credit_minor:
            return gross_minor
    raise ValueError("amount_not_supported")


def gross_up_for_card(credit_minor: int) -> int:
    """Find the AC button amount whose documented 3% fee nets the requested sum."""
    target = Decimal(credit_minor) / 100
    center = _rounded_minor(target / Decimal("0.97"))
    for gross_minor in range(max(1, center - 5), center + 6):
        gross = Decimal(gross_minor) / 100
        fee_minor = _rounded_minor(gross * Decimal("0.03"))
        if gross_minor - fee_minor == credit_minor:
            return gross_minor
    raise ValueError("amount_not_supported")


@dataclass(frozen=True)
class Settings:
    database_path: str
    wallet_id: str
    notification_secret: str
    public_url: str
    commercial_use_approved: bool
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> Settings:
        raw_origins = os.getenv("AXIOM_ALLOWED_ORIGINS", "")
        origins = tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())
        if not origins:
            origins = (
                "tauri://localhost",
                "https://tauri.localhost",
                "http://tauri.localhost",
                "http://localhost:1420",
                "http://127.0.0.1:1420",
            )
        return cls(
            database_path=os.getenv("PAYMENT_DATABASE_PATH", "./data/axiom-payments.sqlite3"),
            wallet_id=os.getenv("YOOMONEY_WALLET_ID", ""),
            notification_secret=load_yoomoney_notification_secret(),
            public_url=os.getenv("PAYMENT_BACKEND_URL", "").rstrip("/"),
            commercial_use_approved=os.getenv("YOOMONEY_COMMERCIAL_USE_APPROVED", "false").lower() == "true",
            allowed_origins=origins,
        )

    @property
    def payments_enabled(self) -> bool:
        return (
            self.commercial_use_approved
            and self.wallet_id.isdigit()
            and bool(self.notification_secret)
            and self.public_url.startswith("https://")
        )

    @property
    def disabled_reason(self) -> str:
        if not self.commercial_use_approved:
            return (
                "Оплата отключена: условия ЮMoney запрещают использовать личный кошелёк "
                "для предпринимательской деятельности."
            )
        if not self.wallet_id.isdigit() or not self.notification_secret or not self.public_url.startswith("https://"):
            return "Оплата ещё не настроена на сервере."
        return "Оплата доступна."


class PaymentStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.database_path != ":memory:":
            Path(settings.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.settings.database_path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    balance_minor INTEGER NOT NULL DEFAULT 0 CHECK (balance_minor >= 0),
                    pro_activated_at TEXT,
                    pro_expires_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_orders (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    type TEXT NOT NULL CHECK (type IN ('balance_topup', 'pro')),
                    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                    expected_pc_withdraw_minor INTEGER NOT NULL CHECK (expected_pc_withdraw_minor > 0),
                    expected_ac_withdraw_minor INTEGER NOT NULL CHECK (expected_ac_withdraw_minor > 0),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'failed', 'expired')),
                    provider TEXT NOT NULL DEFAULT 'yoomoney',
                    label TEXT NOT NULL UNIQUE,
                    provider_operation_id TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    paid_at TEXT,
                    failure_reason TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS payment_orders_user_created
                    ON payment_orders(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS webhook_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
            if "pro_activated_at" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN pro_activated_at TEXT")

    @staticmethod
    def _password_hash(password: str, salt: bytes | None = None) -> str:
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
        return "pbkdf2_sha256${}${}${}".format(
            PASSWORD_ITERATIONS,
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )

    @staticmethod
    def _password_matches(password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt, expected = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), base64.urlsafe_b64decode(salt), int(iterations)
            )
            return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _issue_session(self, db: sqlite3.Connection, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = utc_now()
        db.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (self._token_hash(token), user_id, iso(now + timedelta(days=TOKEN_TTL_DAYS)), iso(now)),
        )
        return token

    def register(self, username: str, password: str) -> tuple[str, str]:
        username = username.strip()
        if not (3 <= len(username) <= 48) or any(
            char not in string.ascii_letters + string.digits + "._-" for char in username
        ):
            raise ValueError("invalid_username")
        if not (12 <= len(password) <= 256):
            raise ValueError("invalid_password")
        user_id = str(uuid.uuid4())
        now = iso(utc_now())
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO users(id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, username, self._password_hash(password), now),
                )
                token = self._issue_session(db, user_id)
                db.commit()
                return user_id, token
        except sqlite3.IntegrityError as exc:
            raise ValueError("username_taken") from exc

    def login(self, username: str, password: str) -> tuple[str, str]:
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (username.strip(),)).fetchone()
            if row is None or not self._password_matches(password, row["password_hash"]):
                db.rollback()
                raise ValueError("invalid_credentials")
            token = self._issue_session(db, row["id"])
            db.commit()
            return row["id"], token

    def authenticate(self, token: str) -> str | None:
        if not token or len(token) > 256:
            return None
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (self._token_hash(token),)
            ).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= utc_now():
            return None
        return str(row["user_id"])

    def revoke_session(self, token: str) -> None:
        if not token or len(token) > 256:
            return
        with closing(self._connect()) as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),))

    def account(self, user_id: str) -> dict:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT id, username, balance_minor, pro_activated_at, pro_expires_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown_user")
            expires = datetime.fromisoformat(row["pro_expires_at"]) if row["pro_expires_at"] else None
            latest = db.execute(
                "SELECT * FROM payment_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,)
            ).fetchone()
        return {
            "id": row["id"],
            "username": row["username"],
            "balance_minor": int(row["balance_minor"]),
            "pro_active": bool(expires and expires > utc_now()),
            "pro_activated_at": row["pro_activated_at"],
            "pro_expires_at": row["pro_expires_at"],
            "payments_available": self.settings.payments_enabled,
            "payments_message": None if self.settings.payments_enabled else self.settings.disabled_reason,
            "latest_payment": self.public_order(latest) if latest else None,
        }

    def create_order(self, user_id: str, order_type: str, amount_rub: str | Decimal | None = None) -> dict:
        if not self.settings.payments_enabled:
            raise PermissionError("payments_disabled")
        if order_type == "balance_topup":
            if amount_rub is None:
                raise ValueError("amount_required")
            amount_minor = rubles_to_minor(amount_rub)
            if amount_minor < MIN_TOPUP_MINOR:
                raise ValueError("minimum_topup")
            if amount_minor > MAX_TOPUP_MINOR:
                raise ValueError("maximum_topup")
            pc_withdraw = gross_up_for_wallet(amount_minor)
            ac_withdraw = gross_up_for_card(amount_minor)
        elif order_type == "pro":
            if amount_rub is not None and rubles_to_minor(amount_rub) != PRO_PRICE_MINOR:
                raise ValueError("invalid_pro_price")
            amount_minor = PRO_PRICE_MINOR
            pc_withdraw = PRO_PRICE_MINOR
            ac_withdraw = PRO_PRICE_MINOR
        else:
            raise ValueError("invalid_order_type")

        order_id = str(uuid.uuid4())
        label = "AX1-" + secrets.token_urlsafe(20).replace("-", "A").replace("_", "B")[:32]
        now = utc_now()
        order = {
            "id": order_id,
            "user_id": user_id,
            "type": order_type,
            "amount_minor": amount_minor,
            "expected_pc_withdraw_minor": pc_withdraw,
            "expected_ac_withdraw_minor": ac_withdraw,
            "status": "pending",
            "label": label,
            "created_at": iso(now),
            "expires_at": iso(now + timedelta(hours=ORDER_TTL_HOURS)),
            "metadata_json": json.dumps({"currency": "RUB", "payment_methods": ["PC", "AC"]}),
        }
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO payment_orders(
                    id, user_id, type, amount_minor, expected_pc_withdraw_minor,
                    expected_ac_withdraw_minor, status, label, created_at, expires_at, metadata_json
                ) VALUES (:id, :user_id, :type, :amount_minor, :expected_pc_withdraw_minor,
                    :expected_ac_withdraw_minor, :status, :label, :created_at, :expires_at, :metadata_json)""",
                order,
            )
            db.commit()
        return self.public_order(order)

    def get_order(self, user_id: str, order_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM payment_orders WHERE id = ? AND user_id = ?", (order_id, user_id)
            ).fetchone()
            if row and row["status"] == "pending" and datetime.fromisoformat(row["expires_at"]) <= utc_now():
                db.execute(
                    "UPDATE payment_orders SET status = 'expired' WHERE id = ? AND status = 'pending'", (order_id,)
                )
                row = db.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
        return self.public_order(row) if row else None

    def get_order_for_checkout(self, order_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
            if row and row["status"] == "pending" and datetime.fromisoformat(row["expires_at"]) <= utc_now():
                db.execute(
                    "UPDATE payment_orders SET status = 'expired' WHERE id = ? AND status = 'pending'", (order_id,)
                )
                row = db.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None

    def public_order(self, order: sqlite3.Row | dict) -> dict:
        order = dict(order)
        return {
            "id": order["id"],
            "type": order["type"],
            "amount_minor": int(order["amount_minor"]),
            "status": order["status"],
            "created_at": order["created_at"],
            "paid_at": order.get("paid_at"),
            "expires_at": order.get("expires_at"),
            "failure_reason": order.get("failure_reason"),
            "payment_url": (
                f"{self.settings.public_url}/checkout/{order['id']}"
                if order["status"] == "pending" and self.settings.payments_enabled
                else None
            ),
        }

    def operation_seen(self, operation_id: str) -> bool:
        with closing(self._connect()) as db:
            return (
                db.execute("SELECT 1 FROM webhook_events WHERE operation_id = ?", (operation_id,)).fetchone()
                is not None
            )

    def process_notification(self, fields: dict[str, str]) -> dict:
        """Apply a signature-verified notification atomically and idempotently."""
        operation_id = fields.get("operation_id", "")
        label = fields.get("label", "")
        if not operation_id:
            raise ValueError("missing_operation_id")
        if len(operation_id) > 128:
            raise ValueError("invalid_operation_id")
        if len(label) > 64:
            raise ValueError("invalid_label")
        try:
            amount_minor = rubles_to_minor(fields.get("amount", ""))
        except ValueError as exc:
            raise ValueError("invalid_amount") from exc
        try:
            withdraw_minor = rubles_to_minor(fields.get("withdraw_amount", ""))
        except ValueError as exc:
            raise ValueError("invalid_withdraw_amount") from exc
        notification_type = fields.get("notification_type", "")
        if notification_type not in {"p2p-incoming", "card-incoming"}:
            raise ValueError("invalid_notification_type")
        if fields.get("currency") != "643":
            raise ValueError("invalid_currency")
        safe_payload = {
            key: fields.get(key, "")
            for key in (
                "notification_type",
                "operation_id",
                "amount",
                "withdraw_amount",
                "currency",
                "datetime",
                "label",
                "codepro",
                "unaccepted",
                "test_notification",
            )
        }
        now = utc_now()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM webhook_events WHERE operation_id = ?", (operation_id,)).fetchone():
                db.commit()
                return {"accepted": True, "duplicate": True, "status": "duplicate"}
            order = db.execute("SELECT * FROM payment_orders WHERE label = ?", (label,)).fetchone()
            verdict = "unknown_order"
            failure_reason: str | None = None
            if order is not None:
                if order["status"] == "expired":
                    verdict = "late_payment"
                    failure_reason = "late_payment"
                elif order["status"] in {"paid", "failed"}:
                    verdict = "order_not_pending"
                elif datetime.fromisoformat(order["expires_at"]) <= now:
                    verdict = "late_payment"
                    failure_reason = "late_payment"
                elif fields.get("test_notification", "false").lower() == "true":
                    verdict = "test_notification"
                elif fields.get("codepro", "").lower() != "false" or fields.get("unaccepted", "").lower() != "false":
                    verdict = "held_or_protected"
                    failure_reason = "payment_not_available"
                else:
                    method = "PC" if notification_type == "p2p-incoming" else "AC"
                    expected_withdraw = int(order[f"expected_{method.lower()}_withdraw_minor"])
                    if withdraw_minor != expected_withdraw:
                        verdict = "wrong_withdraw_amount"
                        failure_reason = "amount_mismatch"
                    elif order["type"] == "balance_topup" and amount_minor < MIN_TOPUP_MINOR:
                        verdict = "under_minimum"
                        failure_reason = "below_minimum"
                    elif order["type"] == "balance_topup" and amount_minor != int(order["amount_minor"]):
                        verdict = "wrong_received_amount"
                        failure_reason = "amount_mismatch"
                    elif order["type"] == "pro" and not (0 < amount_minor <= withdraw_minor):
                        verdict = "invalid_received_amount"
                        failure_reason = "amount_mismatch"
                    else:
                        verdict = "paid"

            db.execute(
                "INSERT INTO webhook_events(operation_id, label, verdict, payload_json, received_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (operation_id, label, verdict, json.dumps(safe_payload, separators=(",", ":")), iso(now)),
            )
            if order is not None and verdict == "paid":
                paid_at = iso(now)
                if order["type"] == "balance_topup":
                    # Use the provider-confirmed incoming amount, never a client value.
                    db.execute(
                        "UPDATE users SET balance_minor = balance_minor + ? WHERE id = ?",
                        (amount_minor, order["user_id"]),
                    )
                else:
                    user = db.execute("SELECT pro_expires_at FROM users WHERE id = ?", (order["user_id"],)).fetchone()
                    current_expiry = (
                        datetime.fromisoformat(user["pro_expires_at"]) if user and user["pro_expires_at"] else None
                    )
                    starts_at = current_expiry if current_expiry and current_expiry > now else now
                    new_expiry = starts_at + timedelta(days=PRO_DAYS)
                    db.execute(
                        "UPDATE users SET pro_activated_at = ?, pro_expires_at = ? WHERE id = ?",
                        (paid_at, iso(new_expiry), order["user_id"]),
                    )
                db.execute(
                    """UPDATE payment_orders SET status = 'paid', paid_at = ?, provider_operation_id = ?,
                       metadata_json = ? WHERE id = ? AND status = 'pending'""",
                    (
                        paid_at,
                        operation_id,
                        json.dumps({"currency": "RUB", "received_minor": amount_minor}, separators=(",", ":")),
                        order["id"],
                    ),
                )
            elif order is not None and failure_reason:
                db.execute(
                    "UPDATE payment_orders SET status = 'failed', failure_reason = ?, provider_operation_id = ? "
                    "WHERE id = ? AND status IN ('pending', 'expired')",
                    (failure_reason, operation_id, order["id"]),
                )
            db.commit()
        return {"accepted": True, "duplicate": False, "status": verdict}


def notification_signature(fields: dict[str, str], secret: str) -> str:
    encoded = "&".join(f"{key}={quote(value, safe='~')}" for key, value in sorted(fields.items()) if key != "sign")
    return hmac.new(secret.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_notification(fields: dict[str, str], secret: str) -> bool:
    supplied = fields.get("sign", "")
    return bool(supplied) and hmac.compare_digest(notification_signature(fields, secret), supplied.lower())


def payment_methods(order: dict) -> list[dict[str, str]]:
    """Return public checkout methods with provider-calculated fixed sums."""
    if order["type"] == "pro":
        pc_sum = ac_sum = PRO_PRICE_MINOR
    else:
        pc_sum = int(order["expected_pc_withdraw_minor"])
        ac_sum = int(order["expected_ac_withdraw_minor"])
    return [
        {"type": "PC", "title": "Кошелёк ЮMoney", "sum": minor_to_rubles(pc_sum)},
        {"type": "AC", "title": "Банковская карта", "sum": minor_to_rubles(ac_sum)},
    ]
