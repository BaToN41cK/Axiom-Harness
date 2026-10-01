import base64
import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from typing import Annotated, Literal, overload
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from axiom_payments import (
    PaymentStore,
    Settings,
    minor_to_rubles,
    payment_methods,
    verify_notification,
)
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
_WEBHOOK_DIAGNOSTIC_FIELDS = frozenset(
    {
        "notification_type",
        "operation_id",
        "amount",
        "withdraw_amount",
        "currency",
        "datetime",
        "sender",
        "codepro",
        "label",
        "unaccepted",
        "test_notification",
        "sha1_hash",
        "sign",
    }
)
_WEBHOOK_REQUIRED_FIELDS = ("operation_id", "amount", "notification_type", "currency")
# Parameters YooMoney used to send and may still send. None of them decides a
# settlement any more, which is exactly why a live notification used to fail here.
_WEBHOOK_LEGACY_FIELDS = ("withdraw_amount", "unaccepted", "sha1_hash")


def _log_webhook_diagnostic(
    request: Request,
    reason: str,
    *,
    fields: dict[str, str] | None = None,
    field_names: set[str] | None = None,
    signature_valid: bool | None = None,
) -> None:
    if fields is not None:
        field_names = set(fields)
    safe_names = sorted((_WEBHOOK_DIAGNOSTIC_FIELDS & field_names) if field_names is not None else ())
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", media_type):
        media_type = "invalid"
    if fields is not None:
        signature_present = bool(fields.get("sign"))
    elif field_names is not None:
        signature_present = "sign" in field_names
    else:
        signature_present = None
    diagnostic = {
        "content_type": media_type[:128],
        "received_field_names": safe_names if field_names is not None else None,
        "required_fields_present": (
            {name: name in field_names for name in _WEBHOOK_REQUIRED_FIELDS} if field_names is not None else None
        ),
        "label_present": "label" in field_names if field_names is not None else None,
        "label_nonempty": bool(fields.get("label")) if fields is not None and "label" in fields else None,
        "signature_present": signature_present,
        "signature_valid": signature_valid,
        "validation_reason": reason,
    }
    logger.warning("yoomoney_webhook_validation %s", json.dumps(diagnostic, separators=(",", ":")))


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=48)
    password: str = Field(min_length=12, max_length=256)


class OAuthProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern="^(github|google)$")


class OAuthRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=256)


class OAuthStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    poll_token: str = Field(min_length=1, max_length=256)


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

    @app.middleware("http")
    async def private_auth_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/v1/auth/", "/auth/")) or request.url.path in {"/v1/me", "/auth/me"}:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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

    @app.get("/auth/me")
    def auth_me(user_id: Annotated[str, Depends(current_user)]) -> dict:
        return store.account(user_id)

    @app.post("/auth/logout", status_code=204)
    def auth_logout(
        authorization: Annotated[str | None, Header()] = None,
        user_id: str = Depends(current_user),
    ) -> Response:
        del user_id
        store.revoke_session((authorization or "")[7:])
        return Response(status_code=204)

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
                "oauth": {provider: oauth_diagnostic(provider) for provider in ("github", "google")},
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

    def oauth_diagnostic(provider: str) -> dict[str, object]:
        """Return safe OAuth configuration diagnostics without exposing values."""
        client_id = settings.github_client_id if provider == "github" else settings.google_client_id
        secret = settings.github_client_secret if provider == "github" else settings.google_client_secret
        configured_uri = settings.github_redirect_uri if provider == "github" else settings.google_redirect_uri
        presence = {
            "client_id": "PRESENT" if client_id else "MISSING",
            "client_secret": "PRESENT" if secret else "MISSING",
            "redirect_uri": "PRESENT" if configured_uri else "MISSING",
        }
        client = settings.oauth_client(provider)
        redirect_uri = settings.oauth_redirect_uri(provider)
        base_value = settings.oauth_redirect_base or settings.public_url
        try:
            redirect = urlsplit(redirect_uri)
            base = urlsplit(base_value or f"{redirect.scheme}://{redirect.netloc}")
        except ValueError:
            return {**presence, "valid": False, "reasons": ["url_parse_error"]}
        reasons: list[str] = []
        if client is None:
            if not (settings.github_client_id if provider == "github" else settings.google_client_id):
                reasons.append("client_id_missing")
            if not (settings.github_client_secret if provider == "github" else settings.google_client_secret):
                reasons.append("client_secret_missing")
        if base.scheme != "https":
            reasons.append("base_not_https")
        if not base.hostname:
            reasons.append("base_host_missing")
        if base.path not in {"", "/"} or base.username or base.password or base.query or base.fragment:
            reasons.append("base_url_invalid")
        if redirect.scheme != "https":
            reasons.append("redirect_not_https")
        if redirect.netloc != base.netloc:
            reasons.append("redirect_host_mismatch")
        if redirect.path not in {f"/auth/{provider}/callback", f"/v1/auth/oauth/{provider}/callback"}:
            reasons.append("redirect_path_invalid")
        if redirect.query or redirect.fragment:
            reasons.append("redirect_url_invalid")
        return {
            **presence,
            "valid": not reasons,
            "reasons": reasons,
        }

    def oauth_configuration(provider: str) -> tuple[str, str, str, list[str]]:
        client = settings.oauth_client(provider)
        redirect_uri = settings.oauth_redirect_uri(provider)
        redirect = urlsplit(redirect_uri)
        base = urlsplit(settings.oauth_redirect_base or settings.public_url or f"{redirect.scheme}://{redirect.netloc}")
        if (
            client is None
            or base.scheme != "https"
            or not base.hostname
            or base.path not in {"", "/"}
            or base.username
            or base.password
            or base.query
            or base.fragment
            or redirect.scheme != "https"
            or redirect.netloc != base.netloc
            or redirect.path not in {f"/auth/{provider}/callback", f"/v1/auth/oauth/{provider}/callback"}
            or redirect.query
            or redirect.fragment
        ):
            raise HTTPException(status_code=503, detail=f"Вход через {provider} ещё не настроен на сервере.")
        if provider == "github":
            return (
                client[0],
                "https://github.com/login/oauth/authorize",
                redirect_uri,
                ["read:user", "user:email"],
            )
        return (
            client[0],
            "https://accounts.google.com/o/oauth2/v2/auth",
            redirect_uri,
            ["openid", "email", "profile"],
        )

    def oauth_browser_start_for(provider: str, state: str, callback_path: str) -> RedirectResponse:
        """Start the existing PKCE flow from a provider-friendly public URL."""
        if provider not in {"github", "google"}:
            raise HTTPException(status_code=400, detail="Неизвестный провайдер входа.")
        client_id, authorization_endpoint, configured_redirect, scopes = oauth_configuration(provider)
        browser_token = os.urandom(32).hex()
        flow = store.begin_oauth(state, provider, browser_token)
        if flow is None or flow["redirect_uri"] != configured_redirect:
            raise HTTPException(status_code=400, detail="Ссылка входа истекла или уже использована.")
        query = {
            "client_id": client_id,
            "redirect_uri": flow["redirect_uri"],
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode("ascii")).digest())
            .decode("ascii")
            .rstrip("="),
            "code_challenge_method": "S256",
        }
        if provider == "google":
            query.update({"access_type": "online", "prompt": "select_account"})
        response = RedirectResponse(url=f"{authorization_endpoint}?{urlencode(query)}", status_code=303)
        response.set_cookie(
            key=f"axiom_oauth_{provider}",
            value=browser_token,
            max_age=600,
            httponly=True,
            secure=True,
            samesite="lax",
            path=urlsplit(flow["redirect_uri"]).path or callback_path,
        )
        return response

    @app.get("/auth/google")
    def google_auth(state: str | None = None) -> RedirectResponse:
        """Compatibility entrypoint for browser clients and provider consoles."""
        oauth_configuration("google")
        if not state:
            state, _, _ = store.create_oauth_flow("google", settings.oauth_redirect_uri("google"))
        return oauth_browser_start_for("google", state, "/auth/google/callback")

    @app.get("/auth/github")
    def github_auth(state: str | None = None) -> RedirectResponse:
        """Compatibility entrypoint for browser clients and provider consoles."""
        oauth_configuration("github")
        if not state:
            state, _, _ = store.create_oauth_flow("github", settings.oauth_redirect_uri("github"))
        return oauth_browser_start_for("github", state, "/auth/github/callback")

    @app.get("/v1/auth/providers")
    def auth_providers() -> dict:
        enabled = {}
        for provider in ("github", "google"):
            try:
                oauth_configuration(provider)
                enabled[provider] = True
            except HTTPException:
                enabled[provider] = False
        return enabled

    @app.post("/v1/auth/oauth/start")
    def oauth_start(body: OAuthProviderRequest, request: Request) -> dict[str, str]:
        limit_auth_attempt(request)
        provider = body.provider
        _, _, redirect_uri, _ = oauth_configuration(provider)
        state, poll_token, _ = store.create_oauth_flow(provider, redirect_uri)
        redirect = urlsplit(redirect_uri)
        browser_base = (
            settings.oauth_redirect_base
            or settings.public_url
            or f"{redirect.scheme}://{redirect.netloc}"
        ).rstrip("/")
        browser_start = f"{browser_base}/auth/{provider}"
        query = {"state": state}
        # Provider parameters stay server-side. The external browser first visits
        # browser-start, which can set its HttpOnly cookie before redirecting.
        return {"authorization_url": f"{browser_start}?{urlencode(query)}", "poll_token": poll_token}

    @app.get("/v1/auth/oauth/browser-start")
    def oauth_browser_start(provider: str, state: str) -> RedirectResponse:
        return oauth_browser_start_for(provider, state, f"/v1/auth/oauth/{provider}/callback")

    @overload
    def provider_request(
        url: str, *, method: str = "GET", form: dict[str, str] | None = None,
        headers: dict[str, str] | None = None, expect_list: Literal[False] = False,
    ) -> dict: ...

    @overload
    def provider_request(
        url: str, *, method: str = "GET", form: dict[str, str] | None = None,
        headers: dict[str, str] | None = None, expect_list: Literal[True],
    ) -> list: ...

    def provider_request(
        url: str, *, method: str = "GET", form: dict[str, str] | None = None,
        headers: dict[str, str] | None = None, expect_list: bool = False,
    ) -> dict | list:
        body = urlencode(form).encode("utf-8") if form is not None else None
        request = UrlRequest(url, data=body, headers=headers or {}, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                value = json.loads(response.read(1_000_000).decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("oauth_provider_unavailable") from exc
        if not isinstance(value, list if expect_list else dict):
            raise ValueError("oauth_provider_invalid_response")
        return value

    def oauth_identity(
        provider: str, code: str, redirect_uri: str, verifier: str
    ) -> tuple[str, str, str | None, str | None]:
        client = settings.oauth_client(provider)
        if client is None:
            raise ValueError("oauth_not_configured")
        if provider == "github":
            token = provider_request(
                "https://github.com/login/oauth/access_token",
                method="POST",
                form={
                    "client_id": client[0],
                    "client_secret": client[1],
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json", "User-Agent": "AXIOM"},
            ).get("access_token")
            if not isinstance(token, str) or not token:
                raise ValueError("oauth_provider_rejected")
            profile = provider_request(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "AXIOM",
                },
            )
            if type(profile.get("id")) is not int or profile["id"] <= 0:
                raise ValueError("oauth_identity_missing")
            subject = str(profile["id"])
            username = str(profile.get("login") or "github-user")
            email = None
            try:
                emails = provider_request(
                    "https://api.github.com/user/emails",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "User-Agent": "AXIOM",
                    },
                    expect_list=True,
                )
                verified = [
                    item for item in emails
                    if isinstance(item, dict) and item.get("verified") is True
                    and isinstance(item.get("email"), str) and item["email"]
                ]
                email = next((item["email"] for item in verified if item.get("primary") is True), None)
                email = email or (verified[0]["email"] if verified else None)
            except ValueError:
                # A private email or a declined user:email scope must not prevent sign-in.
                pass
            return subject, username, email, profile.get("name") if isinstance(profile.get("name"), str) else None
        token = provider_request(
            "https://oauth2.googleapis.com/token",
            method="POST",
            form={
                "client_id": client[0],
                "client_secret": client[1],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        ).get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("oauth_provider_rejected")
        profile = provider_request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        subject = profile.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ValueError("oauth_identity_missing")
        username = str(profile.get("name") or profile.get("email") or "google-user")
        email = profile.get("email") if profile.get("email_verified") is True else None
        if not isinstance(email, str):
            email = None
        return subject, username, email, profile.get("name") if isinstance(profile.get("name"), str) else None

    @app.get("/auth/{provider}/callback")
    @app.get("/v1/auth/oauth/{provider}/callback")
    def oauth_callback(
        provider: str,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        browser_token: str | None = Cookie(default=None, alias="axiom_oauth_github"),
        google_browser_token: str | None = Cookie(default=None, alias="axiom_oauth_google"),
    ) -> HTMLResponse:
        if provider not in {"github", "google"}:
            return HTMLResponse(_checkout_message("OAuth", "Неизвестный провайдер входа."), status_code=400)
        if not state:
            return HTMLResponse(
                _checkout_message("Вход не завершён", "Отсутствует параметр безопасности OAuth."), status_code=400
            )
        browser_token = browser_token if provider == "github" else google_browser_token
        flow = store.consume_oauth_state(state, provider, browser_token or "")
        if flow is None:
            return HTMLResponse(
                _checkout_message("Вход не завершён", "Ссылка входа истекла. Вернитесь в AXIOM и повторите попытку."),
                status_code=400,
            )

        def callback_page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
            result = HTMLResponse(_checkout_message(title, message), status_code=status_code)
            result.delete_cookie(key=f"axiom_oauth_{provider}", path=urlsplit(flow["redirect_uri"]).path)
            return result

        if error or not code:
            store.finish_oauth(state, error="oauth_cancelled")
            return callback_page("Вход отменён", "Вернитесь в AXIOM и выберите способ входа ещё раз.")
        try:
            subject, username, email, display_name = oauth_identity(
                provider, code, flow["redirect_uri"], flow["verifier"]
            )
            if not subject:
                raise ValueError("oauth_identity_missing")
            user_id = store.oauth_login(provider, subject, username, email, display_name)
        except ValueError as exc:
            logger.warning("oauth_callback_failed provider=%s reason=%s", provider, str(exc))
            store.finish_oauth(state, error="oauth_login_failed")
            return callback_page(
                "Вход не завершён",
                "Не удалось подтвердить аккаунт провайдера. Вернитесь в AXIOM и повторите попытку.",
                400,
            )
        except sqlite3.Error:
            logger.error("oauth_callback_database_failed provider=%s", provider)
            return callback_page("Вход не завершён", "Ошибка сервера. Вернитесь в AXIOM и повторите попытку.", 503)
        store.finish_oauth(state, user_id=user_id)
        return callback_page("Вход выполнен", "Можно закрыть эту вкладку и вернуться в AXIOM.")

    @app.post("/v1/auth/oauth/status")
    def oauth_status(body: OAuthStatusRequest) -> dict[str, str | None]:
        result = store.oauth_status(body.poll_token)
        if result is None:
            raise HTTPException(status_code=401, detail="Сеанс входа истёк или не найден.")
        status, value = result
        return {
            "status": status,
            "code": value if status == "success" else None,
            "error": value if status == "error" else None,
        }

    @app.post("/v1/auth/oauth/redeem")
    def oauth_redeem(body: OAuthRedeemRequest) -> dict:
        result = store.redeem_oauth_code(body.code)
        if result is None:
            raise HTTPException(status_code=401, detail="OAuth-код истёк или уже использован.")
        user_id, token = result
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

    @app.post("/v1/payments/pro/balance")
    def create_pro_from_balance(user_id: Annotated[str, Depends(current_user)]) -> dict:
        try:
            account = store.activate_pro_from_balance(user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=402, detail="Недостаточно AXIOM USD-кредитов для AXIOM PRO.") from exc
        return {"account": account}

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
            _log_webhook_diagnostic(request, "unsupported_content_type")
            raise HTTPException(status_code=415, detail="Ожидался form-urlencoded запрос ЮMoney.")
        raw_body = await request.body()
        if len(raw_body) > 65_536:
            raise HTTPException(status_code=413, detail="Уведомление слишком большое.")
        try:
            pairs = parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
        except UnicodeDecodeError as exc:
            _log_webhook_diagnostic(request, "invalid_form_encoding")
            raise HTTPException(status_code=400, detail="invalid_form_encoding") from exc
        except ValueError as exc:
            _log_webhook_diagnostic(request, "malformed_form_body")
            raise HTTPException(status_code=400, detail="malformed_form_body") from exc
        fields: dict[str, str] = {}
        received_field_names = {key for key, _ in pairs}
        for key, value in pairs:
            if key in fields:
                _log_webhook_diagnostic(
                    request,
                    "duplicate_form_field",
                    field_names=received_field_names,
                )
                raise HTTPException(status_code=400, detail="duplicate_form_field")
            fields[key] = value
        if not fields.get("sign"):
            _log_webhook_diagnostic(request, "missing_signature", fields=fields, signature_valid=False)
            raise HTTPException(status_code=401, detail="missing_signature")
        signature_valid = verify_notification(fields, settings.notification_secret)
        if not signature_valid:
            _log_webhook_diagnostic(request, "invalid_signature", fields=fields, signature_valid=False)
            raise HTTPException(status_code=401, detail="invalid_signature")
        try:
            result = store.process_notification(fields)
        except ValueError as exc:
            reason = str(exc)
            safe_reasons = {
                "missing_operation_id",
                "invalid_operation_id",
                "invalid_label",
                "invalid_amount",
                "invalid_withdraw_amount",
                "invalid_notification_type",
                "invalid_currency",
            }
            if reason not in safe_reasons:
                reason = "invalid_notification"
            _log_webhook_diagnostic(request, reason, fields=fields, signature_valid=signature_valid)
            raise HTTPException(status_code=400, detail=reason) from exc
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
