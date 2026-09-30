from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlencode

import axiom_payments
import httpx
import pytest
from axiom_payments import (
    PRO_PRICE_MINOR,
    Settings,
    gross_up_for_card,
    gross_up_for_wallet,
    iso,
    load_yoomoney_notification_secret,
    notification_signature,
    utc_now,
)
from main import create_app

SECRET = "test-notification-secret-do-not-use-in-production"
FILE_SECRET = "synthetic-render-secret-for-tests"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_path=str(tmp_path / "payments.sqlite3"),
        wallet_id="4100118808592904",
        notification_secret=SECRET,
        public_url="https://payments.example.test",
        commercial_use_approved=True,
        allowed_origins=("tauri://localhost",),
    )


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        yield client


async def register(client, username="alice"):
    response = await client.post(
        "/v1/auth/register",
        json={"username": username, "password": "a-long-test-password-123"},
    )
    assert response.status_code == 200
    body = response.json()
    return body["access_token"], body["account"]


async def order_label(settings, order_id):
    with sqlite3.connect(settings.database_path) as db:
        row = db.execute("SELECT label FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
    assert row
    return row[0]


async def notify(client, fields, *, sign=True):
    payload = dict(fields)
    if sign:
        payload["sign"] = notification_signature(payload, SECRET)
    return await client.post(
        "/v1/webhooks/yoomoney",
        content=urlencode(payload),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )


def payment_fields(operation_id, label, *, notification_type="p2p-incoming", amount="100.00", withdraw="101.00"):
    return {
        "notification_type": notification_type,
        "operation_id": operation_id,
        "amount": amount,
        "withdraw_amount": withdraw,
        "currency": "643",
        "datetime": "2026-09-30T12:00:00Z",
        "sender": "41003188981230",
        "codepro": "false",
        "label": label,
        "unaccepted": "false",
    }


def test_notification_secret_loads_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("YOOMONEY_NOTIFICATION_SECRET", "  environment-secret  ")
    monkeypatch.setattr(axiom_payments, "YOOMONEY_NOTIFICATION_SECRET_FILE", tmp_path / "missing-secret")

    assert load_yoomoney_notification_secret() == "environment-secret"


def test_notification_secret_loads_from_render_secret_file(monkeypatch, tmp_path):
    monkeypatch.setenv("YOOMONEY_NOTIFICATION_SECRET", " \t ")
    secret_file = tmp_path / "YOOMONEY_NOTIFICATION_SECRET"
    secret_file.write_text(f"  {FILE_SECRET}\n", encoding="utf-8")
    monkeypatch.setattr(axiom_payments, "YOOMONEY_NOTIFICATION_SECRET_FILE", secret_file)

    assert load_yoomoney_notification_secret() == FILE_SECRET


def test_notification_environment_secret_takes_priority_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv("YOOMONEY_NOTIFICATION_SECRET", "environment-secret")
    secret_file = tmp_path / "YOOMONEY_NOTIFICATION_SECRET"
    secret_file.write_text(FILE_SECRET, encoding="utf-8")
    monkeypatch.setattr(axiom_payments, "YOOMONEY_NOTIFICATION_SECRET_FILE", secret_file)

    assert load_yoomoney_notification_secret() == "environment-secret"


def test_missing_notification_secret_returns_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("YOOMONEY_NOTIFICATION_SECRET", raising=False)
    monkeypatch.setattr(axiom_payments, "YOOMONEY_NOTIFICATION_SECRET_FILE", tmp_path / "missing-secret")

    assert load_yoomoney_notification_secret() == ""


def configure_render_payment_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("YOOMONEY_NOTIFICATION_SECRET", raising=False)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("PAYMENT_DATABASE_PATH", str(tmp_path / "render-payments.sqlite3"))
    monkeypatch.setenv("YOOMONEY_WALLET_ID", "4100118808592904")
    monkeypatch.setenv("PAYMENT_BACKEND_URL", "https://payments.example.test")
    monkeypatch.setenv("YOOMONEY_COMMERCIAL_USE_APPROVED", "true")
    monkeypatch.setattr(
        axiom_payments,
        "YOOMONEY_NOTIFICATION_SECRET_FILE",
        tmp_path / "YOOMONEY_NOTIFICATION_SECRET",
    )
    axiom_payments.YOOMONEY_NOTIFICATION_SECRET_FILE.write_text(FILE_SECRET, encoding="utf-8")


@pytest.mark.asyncio
async def test_healthz_detects_render_secret_file_without_disclosing_it(monkeypatch, tmp_path):
    configure_render_payment_environment(monkeypatch, tmp_path)
    app = create_app(Settings.from_env())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as render_client:
        response = await render_client.get("/healthz")

    diagnostics = response.json()["diagnostics"]
    assert response.status_code == 200
    assert diagnostics["yoomoney_notification_secret_present"] is True
    assert "yoomoney_notification_secret_length" not in diagnostics
    assert diagnostics["environment_config_mode"] == "render/payments-enabled"
    assert FILE_SECRET not in response.text


@pytest.mark.asyncio
async def test_yoomoney_webhook_uses_render_secret_file(monkeypatch, tmp_path):
    configure_render_payment_environment(monkeypatch, tmp_path)
    app = create_app(Settings.from_env())
    fields = payment_fields("render-secret-operation", "AX1-unmatched-label")
    fields["sign"] = notification_signature(fields, FILE_SECRET)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as render_client:
        response = await render_client.post(
            "/v1/webhooks/yoomoney",
            content=urlencode(fields),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "unknown_order"


@pytest.mark.asyncio
async def test_yoomoney_webhook_accepts_official_documented_notification(settings):
    official_fields = {
        "notification_type": "p2p-incoming",
        "operation_id": "441361714955017004",
        "amount": "98.00",
        "withdraw_amount": "100.00",
        "currency": "643",
        "datetime": "2013-12-26T08:28:34Z",
        "sender": "41000000000",
        "codepro": "false",
        "label": "ML23045",
        "unaccepted": "false",
        "sha1_hash": "ac13833bd6ba9eff1fa9e4bed76f3d6ebb57f6c0",
    }
    official_signature = "a452af731650e2c5b39abcdc7c28dd27db7b3b654c2230ad2c386e64afb98605"
    assert notification_signature(official_fields, "secret123") == official_signature

    app = create_app(replace(settings, notification_secret="secret123"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as official_client:
        response = await official_client.post(
            "/v1/webhooks/yoomoney",
            content=urlencode({**official_fields, "sign": official_signature}),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "unknown_order"


@pytest.mark.asyncio
async def test_yoomoney_webhook_acknowledges_signed_notification_without_label(client):
    fields = payment_fields("unlabeled-operation", "")
    response = await notify(client, fields)

    assert response.status_code == 200
    assert response.json()["status"] == "unknown_order"


@pytest.mark.parametrize(("credit", "wallet_sum", "card_sum"), [(10_000, 10_100, 10_309), (25_000, 25_250, 25_773)])
def test_documented_gross_up_preserves_confirmed_topup(credit, wallet_sum, card_sum):
    assert gross_up_for_wallet(credit) == wallet_sum
    assert gross_up_for_card(credit) == card_sum


@pytest.mark.asyncio
async def test_topup_100_rub_creates_server_order_and_dynamic_yoomoney_link(client):
    token, account = await register(client)
    response = await client.post(
        "/v1/payments/topup",
        json={"type": "balance_topup", "amount_rub": "100.00"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    payment = response.json()["payment"]
    assert payment["amount_minor"] == 10_000
    assert payment["status"] == "pending"
    assert payment["payment_url"] == f"https://payments.example.test/checkout/{payment['id']}"
    assert "label" not in payment
    assert account["balance_minor"] == 0
    page = await client.get(f"/checkout/{payment['id']}")
    assert page.status_code == 200
    assert "quickpay/confirm" in page.text
    assert "4100118808592904" in page.text
    assert "101.00" in page.text
    assert "103.09" in page.text
    assert "successURL" in page.text


@pytest.mark.asyncio
async def test_topup_below_100_rub_is_rejected_server_side(client):
    token, _ = await register(client)
    response = await client.post(
        "/v1/payments/topup",
        json={"type": "balance_topup", "amount_rub": "99.99"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert "100" in response.json()["detail"]


@pytest.mark.asyncio
async def test_pro_price_is_fixed_and_client_cannot_override_it(client):
    token, account = await register(client)
    order = await client.post("/v1/payments/pro", json={"type": "pro"}, headers={"authorization": f"Bearer {token}"})
    assert order.status_code == 201
    assert order.json()["payment"]["amount_minor"] == PRO_PRICE_MINOR
    wrong_price = await client.post(
        "/v1/payments/pro",
        json={"type": "pro", "amount_rub": "989"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert wrong_price.status_code == 422
    assert account["pro_active"] is False


@pytest.mark.asyncio
async def test_successful_balance_notification_credits_confirmed_amount_once(client, settings):
    token, _ = await register(client)
    created = await client.post(
        "/v1/payments/topup",
        json={"type": "balance_topup", "amount_rub": "100"},
        headers={"authorization": f"Bearer {token}"},
    )
    order = created.json()["payment"]
    label = await order_label(settings, order["id"])
    fields = payment_fields("operation-001", label)
    first = await notify(client, fields)
    duplicate = await notify(client, fields)
    second_operation = await notify(client, payment_fields("operation-002", label))
    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert second_operation.json()["status"] == "order_not_pending"
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    assert account["balance_minor"] == 10_000
    current = await client.get(f"/v1/payments/{order['id']}", headers={"authorization": f"Bearer {token}"})
    assert current.json()["payment"]["status"] == "paid"


@pytest.mark.asyncio
async def test_card_notification_uses_card_amount_and_fee_validation(client, settings):
    token, _ = await register(client)
    order = (
        await client.post(
            "/v1/payments/topup",
            json={"type": "balance_topup", "amount_rub": "100"},
            headers={"authorization": f"Bearer {token}"},
        )
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    response = await notify(
        client,
        payment_fields("card-operation", label, notification_type="card-incoming", withdraw="103.09"),
    )
    assert response.status_code == 200
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    assert account["balance_minor"] == 10_000


@pytest.mark.asyncio
async def test_duplicate_pro_notification_does_not_extend_twice(client, settings):
    token, _ = await register(client)
    order = (
        await client.post("/v1/payments/pro", json={"type": "pro"}, headers={"authorization": f"Bearer {token}"})
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    fields = payment_fields("pro-operation-1", label, amount="980.20", withdraw="990.00")
    await notify(client, fields)
    await notify(client, fields)
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    expiry = __import__("datetime").datetime.fromisoformat(account["pro_expires_at"])
    assert account["pro_active"] is True
    assert account["pro_activated_at"] is not None
    assert timedelta(days=29, hours=23) < expiry - utc_now() <= timedelta(days=30, seconds=2)


@pytest.mark.asyncio
async def test_already_active_pro_extends_existing_expiration(client, settings):
    token, account = await register(client)
    existing = utc_now() + timedelta(days=9)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("UPDATE users SET pro_expires_at = ? WHERE id = ?", (iso(existing), account["id"]))
    order = (
        await client.post("/v1/payments/pro", json={"type": "pro"}, headers={"authorization": f"Bearer {token}"})
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    await notify(client, payment_fields("pro-operation-2", label, amount="980.20", withdraw="990.00"))
    refreshed = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    expiry = __import__("datetime").datetime.fromisoformat(refreshed["pro_expires_at"])
    assert timedelta(days=38, hours=23) < expiry - utc_now() <= timedelta(days=39, seconds=2)


@pytest.mark.asyncio
async def test_expired_pro_is_reactivated_for_30_days(client, settings):
    token, account = await register(client)
    old_expiry = utc_now() - timedelta(days=2)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("UPDATE users SET pro_expires_at = ? WHERE id = ?", (iso(old_expiry), account["id"]))
    order = (
        await client.post("/v1/payments/pro", json={"type": "pro"}, headers={"authorization": f"Bearer {token}"})
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    await notify(client, payment_fields("pro-operation-3", label, amount="980.20", withdraw="990.00"))
    refreshed = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    expiry = __import__("datetime").datetime.fromisoformat(refreshed["pro_expires_at"])
    assert refreshed["pro_active"] is True
    assert timedelta(days=29, hours=23) < expiry - utc_now() <= timedelta(days=30, seconds=2)


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_without_recording_or_credit(client, settings):
    token, _ = await register(client)
    order = (
        await client.post(
            "/v1/payments/topup",
            json={"type": "balance_topup", "amount_rub": "100"},
            headers={"authorization": f"Bearer {token}"},
        )
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    response = await notify(client, payment_fields("forged-operation", label), sign=False)
    assert response.status_code == 401
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM webhook_events").fetchone()[0] == 0
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    assert account["balance_minor"] == 0


@pytest.mark.asyncio
async def test_invalid_notification_shape_is_rejected(client):
    fields = {"operation_id": "bad", "label": "bad", "amount": "100.00", "withdraw_amount": "100.00", "currency": "643"}
    response = await notify(client, fields)
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_notification_type"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"amount": "not-an-amount"}, "invalid_amount"),
        ({"withdraw_amount": "not-an-amount"}, "invalid_withdraw_amount"),
        ({"notification_type": "unknown-type"}, "invalid_notification_type"),
        ({"currency": "840"}, "invalid_currency"),
    ],
)
@pytest.mark.asyncio
async def test_webhook_returns_safe_validation_reason(client, overrides, reason):
    fields = payment_fields("invalid-shape-operation", "AX1-test-label")
    fields.update(overrides)
    response = await notify(client, fields)

    assert response.status_code == 400
    assert response.json()["detail"] == reason
    assert "not-an-amount" not in response.text


@pytest.mark.asyncio
async def test_webhook_returns_safe_reason_for_malformed_form(client):
    response = await client.post(
        "/v1/webhooks/yoomoney",
        content="not-a-form-field",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "malformed_form_body"


@pytest.mark.asyncio
async def test_webhook_returns_safe_reason_for_duplicate_form_field(client):
    response = await client.post(
        "/v1/webhooks/yoomoney",
        content="operation_id=first&operation_id=second",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "duplicate_form_field"


@pytest.mark.asyncio
async def test_wrong_amount_marks_order_failed_and_never_credits(client, settings):
    token, _ = await register(client)
    order = (
        await client.post(
            "/v1/payments/topup",
            json={"type": "balance_topup", "amount_rub": "100"},
            headers={"authorization": f"Bearer {token}"},
        )
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    response = await notify(client, payment_fields("wrong-amount", label, amount="101.00"))
    assert response.status_code == 200
    current = (await client.get(f"/v1/payments/{order['id']}", headers={"authorization": f"Bearer {token}"})).json()[
        "payment"
    ]
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    assert current["status"] == "failed"
    assert current["failure_reason"] == "amount_mismatch"
    assert account["balance_minor"] == 0


@pytest.mark.asyncio
async def test_incoming_payment_below_100_is_recorded_but_not_credited(client, settings):
    token, _ = await register(client)
    order = (
        await client.post(
            "/v1/payments/topup",
            json={"type": "balance_topup", "amount_rub": "100"},
            headers={"authorization": f"Bearer {token}"},
        )
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    response = await notify(client, payment_fields("under-minimum", label, amount="99.99"))
    assert response.status_code == 200
    current = (await client.get(f"/v1/payments/{order['id']}", headers={"authorization": f"Bearer {token}"})).json()[
        "payment"
    ]
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    assert current["status"] == "failed"
    assert current["failure_reason"] == "below_minimum"
    assert account["balance_minor"] == 0
    with sqlite3.connect(settings.database_path) as db:
        assert (
            db.execute("SELECT verdict FROM webhook_events WHERE operation_id='under-minimum'").fetchone()[0]
            == "under_minimum"
        )


@pytest.mark.asyncio
async def test_wrong_pro_charge_does_not_activate(client, settings):
    token, _ = await register(client)
    order = (
        await client.post("/v1/payments/pro", json={"type": "pro"}, headers={"authorization": f"Bearer {token}"})
    ).json()["payment"]
    label = await order_label(settings, order["id"])
    response = await notify(client, payment_fields("wrong-pro-charge", label, amount="979.00", withdraw="989.00"))
    assert response.status_code == 200
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    assert account["pro_active"] is False


@pytest.mark.asyncio
async def test_unknown_order_is_recorded_but_cannot_change_account(client, settings):
    token, _ = await register(client)
    response = await notify(client, payment_fields("unknown-operation", "AX1-unknown-label"))
    assert response.status_code == 200
    assert response.json()["status"] == "unknown_order"
    account = (await client.get("/v1/me", headers={"authorization": f"Bearer {token}"})).json()
    assert account["balance_minor"] == 0
    assert account["pro_active"] is False
    with sqlite3.connect(settings.database_path) as db:
        assert (
            db.execute("SELECT verdict FROM webhook_events WHERE operation_id='unknown-operation'").fetchone()[0]
            == "unknown_order"
        )


@pytest.mark.asyncio
async def test_order_is_bound_to_authenticated_owner(client):
    first_token, _ = await register(client, "first")
    second_token, _ = await register(client, "second")
    order = (
        await client.post(
            "/v1/payments/topup",
            json={"type": "balance_topup", "amount_rub": "100"},
            headers={"authorization": f"Bearer {first_token}"},
        )
    ).json()["payment"]
    response = await client.get(f"/v1/payments/{order['id']}", headers={"authorization": f"Bearer {second_token}"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_client_cannot_directly_set_balance_or_activate_pro(client):
    token, initial = await register(client)
    headers = {"authorization": f"Bearer {token}"}
    forged_order = await client.post(
        "/v1/payments/pro", json={"type": "pro", "pro_active": True, "balance_minor": 5_000_000}, headers=headers
    )
    forged_profile = await client.patch(
        "/v1/me", json={"pro_active": True, "balance_minor": 99_000_000}, headers=headers
    )
    after = (await client.get("/v1/me", headers=headers)).json()
    assert forged_order.status_code == 422
    assert forged_profile.status_code == 405
    assert after["balance_minor"] == initial["balance_minor"] == 0
    assert after["pro_active"] is False


@pytest.mark.asyncio
async def test_disabled_personal_wallet_flow_fails_closed(tmp_path):
    blocked_settings = Settings(
        database_path=str(tmp_path / "blocked.sqlite3"),
        wallet_id="4100118808592904",
        notification_secret=SECRET,
        public_url="https://payments.example.test",
        commercial_use_approved=False,
        allowed_origins=("tauri://localhost",),
    )
    app = create_app(blocked_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as blocked_client:
        token, account = await register(blocked_client)
        response = await blocked_client.post(
            "/v1/payments/topup",
            json={"type": "balance_topup", "amount_rub": "100"},
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503
        assert account["payments_available"] is False
