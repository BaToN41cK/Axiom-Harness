# YooMoney payments for AXIOM

## Provider constraint: do not enable this personal-wallet flow for sales

The requested recipient is a personal YooMoney wallet. YooMoney's current wallet safety guidance says wallets are for personal purposes and prohibits their use for entrepreneurial activity. Selling AXIOM PRO or paid balance through this wallet is a commercial use. The backend therefore defaults to **disabled**, and the current personal-wallet requirement cannot be used to launch these sales under YooMoney's published terms. Keep `YOOMONEY_COMMERCIAL_USE_APPROVED=false`. Ask YooMoney support for a written determination or use a payment product/account whose terms permit software subscriptions. The guard variable only enables checkout after that question is resolved; setting it does not override YooMoney's terms.

Source: [YooMoney wallet safety guidance](https://yoomoney.ru/document/obshaya-bezopasnost-i-zashita-koshelka).

## Verified payment path

The simple URL `https://yoomoney.ru/to/4100118808592904` has no per-order identifier. A payment made through that URL cannot be reliably assigned to an AXIOM account and must never activate PRO.

The implementation uses YooMoney's documented payment-button form instead:

1. The authenticated AXIOM account creates a server-side pending order.
2. The backend issues a random, unique label (under YooMoney's 64-character limit) and a public checkout URL. The label maps to the order and its owner only in the backend database.
3. The hosted checkout page submits a YooMoney `quickpay/confirm` form with the configured wallet, fixed amount, payment type, order label, and return URL. The payer chooses a YooMoney wallet or bank card. YooMoney collects any card information; AXIOM never receives it.
4. YooMoney sends `POST /v1/webhooks/yoomoney`. The backend verifies the official HMAC-SHA256 `sign` over all URL-encoded notification parameters except `sign`, sorted by name, then validates currency, incoming type, label, unique operation ID, expected sender debit and recipient amount.
5. One SQLite transaction records the operation, changes the order, and credits the confirmed amount or extends PRO. A duplicate operation ID cannot apply a second time.

The QR in AXIOM contains only the public HTTPS checkout URL. The hosted page displays the actual charge for the selected method. For top-ups, YooMoney's documented button fees are recipient-side (wallet: 1%; card: 3%), so the backend calculates the form sum to deliver the requested top-up amount. If the signed notification's received amount does not match the pending order, or is below 100 ₽, it is recorded and the order fails without a credit. PRO costs exactly 990 ₽ to the payer (`withdraw_amount`); recipient fees reduce what reaches the wallet but do not change the purchase price.

The notification protocol does not contain a separate `status` field. The signed incoming-payment notification is treated as the provider's confirmation event; `unaccepted=true`, code-protected, test, wrong-currency, wrong-type, wrong-label, wrong-amount, and duplicate events do not grant value. A browser return is informational only.

Primary docs: [payment-button form and fee parameters](https://yoomoney.ru/docs/payment-buttons/using-api/forms), [HTTP notifications and signature verification](https://yoomoney.ru/docs/payment-buttons/using-api/notifications), [HTTP notification settings](https://yoomoney.ru/document/http-uvedomleniya).

## Backend and schema

The optional FastAPI service lives in `payment-backend/` and does not change AXIOM's local chat runtime. It uses one SQLite database on a persistent server disk and must run as a single service instance.

- `users`: account ID, username, PBKDF2 password hash, balance in kopecks, PRO activation and expiration timestamps.
- `sessions`: only a SHA-256 hash of each random bearer token and its expiry.
- `payment_orders`: owner, type, expected amount, status, unique YooMoney label, unique operation ID, timestamps, and minimal reconciliation metadata.
- `webhook_events`: one row per signed provider operation, including unmatched, duplicate-order, and rejected-amount events. Sender names, phone numbers, addresses, card data, and the whole callback body are not stored.

New desktop accounts use a username and password because AXIOM currently has no shared account/auth service. Passwords are PBKDF2-HMAC-SHA256 hashed. A bearer session token is kept in this desktop user's local storage, expires after 30 days, and is never accepted as a user ID. There is no password-reset flow yet; users should retain their password. The server exposes no API for a client to edit its balance or PRO state.

### API endpoints

- `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/logout`
- `GET /v1/me` — current balance, PRO status/expiry, latest order, and payment availability
- `POST /v1/payments/topup` — server validates 100–100,000 ₽ and creates a pending order
- `POST /v1/payments/pro` — amount is fixed server-side at 990 ₽
- `GET /v1/payments/{order_id}` — owner-scoped public status and refreshed account fields
- `POST /v1/webhooks/yoomoney` — signed YooMoney callback
- `GET /checkout/{order_id}` — hosted form; `GET /checkout/{order_id}/return` — informational return page
- `GET /healthz`

## Environment configuration

Set these in the hosting platform's secret/environment settings. The backend reads `YOOMONEY_NOTIFICATION_SECRET` from the environment first, then falls back to the Render Secret File at `/etc/secrets/YOOMONEY_NOTIFICATION_SECRET`. Do not commit actual values or create a production `.env` file.

| Variable | Value / purpose |
| --- | --- |
| `YOOMONEY_WALLET_ID` | Public receiving wallet ID, `4100118808592904` |
| `YOOMONEY_NOTIFICATION_SECRET` | Secret generated in the wallet's HTTP-notification settings; read from the environment or Render Secret File; never place in AXIOM desktop builds |
| `PAYMENT_BACKEND_URL` | Public HTTPS base URL of this service, e.g. `https://axiom-harness.onrender.com` |
| `PAYMENT_DATABASE_PATH` | Persistent path, e.g. `/var/data/axiom-payments.sqlite3` |
| `YOOMONEY_COMMERCIAL_USE_APPROVED` | Defaults to `false`; keep false unless YooMoney confirms this use is permitted for this wallet |
| `AXIOM_ALLOWED_ORIGINS` | Optional comma-separated Tauri/dev origins. A restrictive Tauri allowlist is built in by default. |

The only payment-provider secret is `YOOMONEY_NOTIFICATION_SECRET`; the wallet ID is public. Both `axiom --gui` (Vite dev) and production desktop builds default to the public backend at `https://axiom-harness.onrender.com` via `DEFAULT_BACKEND_URL` in `desktop/src/lib/payments.ts`. A custom URL still wins when set at startup or build time:

```powershell
$env:VITE_PAYMENT_BACKEND_URL = "https://axiom-harness.onrender.com"
npm --prefix desktop run build
```

For local dev (`vite dev`), the same default applies. Set `VITE_PAYMENT_BACKEND_URL` explicitly only to use another backend.

That URL is public configuration, not a secret. No YooMoney credentials or notification secret go into the frontend or desktop binary.

## Deployment on Render

Render documents Python FastAPI web services and persistent disks. Free web services do not support persistent disks; SQLite must not be kept on an ephemeral filesystem. The current Render disk rate is $0.25/GB/month in addition to the selected paid web-service compute plan. Review current rates before creating the service.

1. Push this repository to a Git provider accessible to Render.
2. In Render, choose **New → Web Service**, select the repository, choose **Python 3**, and set **Root Directory** to `payment-backend`.
3. Set **Build Command** to `pip install -r requirements.txt`.
4. Set **Start Command** to `uvicorn main:app --host 0.0.0.0 --port $PORT`.
5. Select a paid web-service plan with one service instance. Under **Advanced → Disk**, add a 1 GB persistent disk mounted at `/var/data`.
6. Add the configuration above in the service settings. Set `PAYMENT_DATABASE_PATH=/var/data/axiom-payments.sqlite3`, `PAYMENT_BACKEND_URL` to the service's HTTPS URL, and keep `YOOMONEY_COMMERCIAL_USE_APPROVED=false` until the provider-use restriction is resolved. Store the notification secret as an Environment variable or as a Secret File named `YOOMONEY_NOTIFICATION_SECRET`.
7. Deploy and confirm `https://<service>.onrender.com/healthz` returns `{"status":"ok"}`.
8. Build AXIOM with the default public URL, or set `VITE_PAYMENT_BACKEND_URL` to override it.

Render references: [FastAPI deployment](https://render.com/docs/deploy-fastapi), [persistent disks](https://render.com/docs/disks), [environment variables/secrets](https://render.com/docs/configure-environment-variables), [pricing](https://render.com/pricing).

## YooMoney setup (only after provider terms allow it)

1. In the wallet's **HTTP notifications** settings, set the callback URL to `https://<service>/v1/webhooks/yoomoney`.
2. Generate/copy the notification secret there and store it in Render as a Secret File named `YOOMONEY_NOTIFICATION_SECRET` (mounted at `/etc/secrets/YOOMONEY_NOTIFICATION_SECRET`) or as the `YOOMONEY_NOTIFICATION_SECRET` environment variable. Never send it to AXIOM or commit it.
3. Use YooMoney's **Test** notification button. The service will accept a correctly signed test event but will not mark an order paid.
4. Enable notifications and confirm Render receives a valid HTTPS callback. YooMoney documents retries if the endpoint does not return HTTP 200.
5. Do not set `YOOMONEY_COMMERCIAL_USE_APPROVED=true` while relying only on the personal wallet under the currently published restriction.

The wallet supports only one notification URL. This service routes orders by `label`, so multiple order types share the endpoint. Its label is generated by the server, never accepted from the desktop client.

## Tests

Run the backend's automated payment checks with:

```powershell
$env:PYTHONPATH = "payment-backend"
python -m pytest -q payment-backend/test_payments.py
```

The tests cover amount rules, source fees, signature validation, unknown labels, owner scoping, payment status, top-up and PRO fulfillment, duplicate operations, PRO extension/reactivation, and refusal of client-side balance/PRO edits. They use a local test secret and synthetic signed notifications; they do not contact YooMoney.
