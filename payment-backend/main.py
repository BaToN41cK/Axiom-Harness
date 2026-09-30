import html
import os
import time
from collections import defaultdict, deque
from typing import Annotated
from urllib.parse import parse_qsl

from axiom_payments import PaymentStore, Settings, minor_to_rubles, payment_methods, verify_notification
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=48)
    password: str = Field(min_length=12, max_length=256)


class TopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(pattern="^balance_topup$")
    amount_rub: str = Field(min_length=1, max_length=16)


class ProRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(pattern="^pro$")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = PaymentStore(settings)
    app = FastAPI(title="AXIOM Payments", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.settings = settings
    auth_attempts: dict[str, deque[float]] = defaultdict(deque)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    def current_user(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Требуется вход в AXIOM.")
        user_id = store.authenticate(authorization[7:])
        if not user_id:
            raise HTTPException(status_code=401, detail="Сессия истекла. Войдите снова.")
        return user_id

    def limit_auth_attempt(request: Request) -> None:
        bucket = auth_attempts[request.client.host if request.client else "unknown"]
        now = time.monotonic()
        while bucket and bucket[0] <= now - 60:
            bucket.popleft()
        if len(bucket) >= 10:
            raise HTTPException(status_code=429, detail="Слишком много попыток входа. Подождите минуту.")
        bucket.append(now)

    @app.get("/healthz")
    def health() -> dict[str, object]:
        environment = "render" if os.getenv("RENDER", "").lower() == "true" else "local"
        payment_mode = "payments-enabled" if settings.payments_enabled else "payments-disabled"
        return {
            "status": "ok",
            "diagnostics": {
                "yoomoney_notification_secret_present": bool(settings.notification_secret),
                "yoomoney_wallet_id_present": bool(settings.wallet_id),
                "payment_backend_url_present": bool(settings.public_url),
                "environment_config_mode": f"{environment}/{payment_mode}",
            },
        }

    @app.post("/v1/auth/register")
    def register(body: AuthRequest, request: Request) -> dict:
        limit_auth_attempt(request)
        try:
            user_id, token = store.register(body.username, body.password)
        except ValueError as exc:
            code = str(exc)
            status = 409 if code == "username_taken" else 422
            detail = (
                "Это имя пользователя уже занято."
                if status == 409
                else "Имя пользователя или пароль не подходят требованиям."
            )
            raise HTTPException(status_code=status, detail=detail) from exc
        return {"access_token": token, "token_type": "bearer", "account": store.account(user_id)}

    @app.post("/v1/auth/login")
    def login(body: AuthRequest, request: Request) -> dict:
        limit_auth_attempt(request)
        try:
            user_id, token = store.login(body.username, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль.") from exc
        return {"access_token": token, "token_type": "bearer", "account": store.account(user_id)}

    @app.get("/v1/me")
    def me(user_id: Annotated[str, Depends(current_user)]) -> dict:
        return store.account(user_id)

    @app.post("/v1/auth/logout", status_code=204)
    def logout(authorization: Annotated[str | None, Header()] = None, user_id: str = Depends(current_user)) -> Response:
        del user_id
        store.revoke_session((authorization or "")[7:])
        return Response(status_code=204)

    @app.post("/v1/payments/topup", status_code=201)
    def create_topup(body: TopupRequest, user_id: Annotated[str, Depends(current_user)]) -> dict:
        try:
            order = store.create_order(user_id, "balance_topup", body.amount_rub)
        except PermissionError as exc:
            raise HTTPException(status_code=503, detail=settings.disabled_reason) from exc
        except ValueError as exc:
            code = str(exc)
            messages = {
                "invalid_amount": "Введите сумму в рублях с точностью до копеек.",
                "minimum_topup": "Минимальное пополнение — 100 ₽.",
                "maximum_topup": "Максимальное пополнение за один раз — 100 000 ₽.",
                "amount_not_supported": (
                    "Для этой суммы YooMoney не может точно рассчитать зачисление. "
                    "Попробуйте сумму на копейку больше или меньше."
                ),
            }
            raise HTTPException(status_code=422, detail=messages.get(code, "Некорректная сумма.")) from exc
        return {"payment": order}

    @app.post("/v1/payments/pro", status_code=201)
    def create_pro(body: ProRequest, user_id: Annotated[str, Depends(current_user)]) -> dict:
        try:
            order = store.create_order(user_id, "pro")
        except PermissionError as exc:
            raise HTTPException(status_code=503, detail=settings.disabled_reason) from exc
        return {"payment": order}

    @app.get("/v1/payments/{order_id}")
    def payment_status(order_id: str, user_id: Annotated[str, Depends(current_user)]) -> dict:
        order = store.get_order(user_id, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Платёж не найден.")
        return {"payment": order, "account": store.account(user_id)}

    @app.post("/v1/webhooks/yoomoney")
    async def yoomoney_webhook(request: Request) -> JSONResponse:
        if not settings.notification_secret:
            raise HTTPException(status_code=503, detail="Уведомления ЮMoney ещё не настроены.")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(status_code=415, detail="Ожидался form-urlencoded запрос ЮMoney.")
        raw_body = await request.body()
        if len(raw_body) > 65_536:
            raise HTTPException(status_code=413, detail="Уведомление слишком большое.")
        try:
            pairs = parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Некорректное уведомление.") from exc
        fields: dict[str, str] = {}
        for key, value in pairs:
            if key in fields:
                raise HTTPException(status_code=400, detail="В уведомлении повторяется поле.")
            fields[key] = value
        if not verify_notification(fields, settings.notification_secret):
            raise HTTPException(status_code=401, detail="Подпись уведомления не прошла проверку.")
        try:
            result = store.process_notification(fields)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Поля уведомления некорректны.") from exc
        return JSONResponse(result)

    @app.get("/checkout/{order_id}", response_class=HTMLResponse)
    def checkout(order_id: str) -> HTMLResponse:
        if not settings.payments_enabled:
            raise HTTPException(status_code=404, detail="Страница оплаты не найдена.")
        order = store.get_order_for_checkout(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Заказ не найден.")
        if order["status"] != "pending":
            return HTMLResponse(
                _checkout_message("Заказ больше не ожидает оплату", "Вернитесь в AXIOM и обновите статус платежа.")
            )
        methods = payment_methods(order)
        action = "https://yoomoney.ru/quickpay/confirm"
        success_url = html.escape(f"{settings.public_url}/checkout/{order_id}/return", quote=True)
        forms = []
        for method in methods:
            payment_type = html.escape(method["type"], quote=True)
            title = html.escape(method["title"])
            total = html.escape(method["sum"], quote=True)
            action_safe = html.escape(action, quote=True)
            receiver = html.escape(settings.wallet_id, quote=True)
            label = html.escape(order["label"], quote=True)
            forms.append(
                f"""<form method="post" action="{action_safe}">
                  <input type="hidden" name="receiver" value="{receiver}">
                  <input type="hidden" name="quickpay-form" value="button">
                  <input type="hidden" name="paymentType" value="{payment_type}">
                  <input type="hidden" name="sum" value="{total}">
                  <input type="hidden" name="label" value="{label}">
                  <input type="hidden" name="successURL" value="{success_url}">
                  <button type="submit">{title} · {total} ₽</button>
                </form>"""
            )
        amount = html.escape(minor_to_rubles(int(order["amount_minor"])))
        description = "Зачисление на баланс AXIOM" if order["type"] == "balance_topup" else "AXIOM PRO на 30 дней"
        body = f"""<h1>{html.escape(description)}</h1>
          <p class="price">{amount} ₽</p>
          <p>Выберите способ оплаты. Данные карты вводятся только на сайте ЮMoney.</p>
          {"".join(forms)}
          <p class="note">После возврата дождитесь проверки уведомления ЮMoney в приложении AXIOM.
          Сам возврат не подтверждает оплату.</p>"""
        return HTMLResponse(_html_page(body))

    @app.get("/checkout/{order_id}/return", response_class=HTMLResponse)
    def checkout_return(order_id: str) -> HTMLResponse:
        if store.get_order_for_checkout(order_id) is None:
            raise HTTPException(status_code=404, detail="Заказ не найден.")
        return HTMLResponse(
            _checkout_message(
                "Проверяем платёж",
                "Вернитесь в AXIOM. Баланс и AXIOM PRO обновятся после проверки серверного уведомления ЮMoney.",
            )
        )

    return app


def _html_page(body: str) -> str:
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Оплата AXIOM</title>
        <style>
        :root{{color-scheme:dark light;font:16px system-ui,sans-serif}}
        body{{max-width:440px;margin:8vh auto;padding:24px}}
        main{{border:1px solid #8885;border-radius:16px;padding:28px}}
        h1{{font-size:20px}}.price{{font-size:28px;font-weight:700}}
        form{{margin:12px 0}}
        button{{width:100%;padding:14px;border:0;border-radius:10px;background:#7568ff;
          color:white;font-size:16px;cursor:pointer}}
        .note{{font-size:13px;opacity:.75;line-height:1.5}}
      </style><main>{body}</main></html>"""


def _checkout_message(title: str, message: str) -> str:
    return _html_page(f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>")


app = create_app()
