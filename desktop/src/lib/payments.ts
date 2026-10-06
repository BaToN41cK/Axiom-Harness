export type PaymentType = "balance_topup" | "pro";
export type PaymentStatus = "pending" | "paid" | "failed" | "expired";

export { axiomUsd, rubMinorToAxiomUsdMinor } from "./currency";

export interface Payment {
  id: string;
  type: PaymentType;
  amount_minor: number;
  status: PaymentStatus;
  created_at: string;
  paid_at: string | null;
  expires_at: string | null;
  failure_reason: string | null;
  received_rub_minor: number | null;
  credited_axiom_usd_minor: number | null;
  payment_url: string | null;
}

export interface Account {
  id: string;
  username: string;
  balance_minor: number;
  pro_active: boolean;
  pro_activated_at: string | null;
  pro_expires_at: string | null;
  payments_available: boolean;
  payments_message: string | null;
  latest_payment: Payment | null;
}

// Public HTTPS URL used in dev and production; an explicit Vite URL overrides it.
// Do not put YooMoney credentials, keys or tokens in the frontend.
const DEFAULT_BACKEND_URL = "https://axiom-harness.onrender.com";

const API_BASE = (
  import.meta.env.VITE_PAYMENT_BACKEND_URL || DEFAULT_BACKEND_URL
).replace(/\/$/, "");
const TOKEN_KEY = "axiom.payments.session.v1";

export const paymentBackendConfigured = Boolean(API_BASE);
export const paymentToken = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function api<T>(path: string, options: { token?: string | null; body?: unknown } = {}): Promise<T> {
  if (!API_BASE) throw new Error("Платёжный сервер не указан в этой сборке AXIOM.");
  // A VPN exit-country switch drops in-flight connections. Transient network
  // failures get a short backoff retry before surfacing an error — the same
  // idea as the Python core's retry_async.
  const delays = [0, 1000, 3000];
  const retryable = (status: number) => status >= 500 || status === 429 || status === 408;
  let lastError: unknown = null;
  for (let attempt = 0; attempt < delays.length; attempt++) {
    if (delays[attempt]) await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
    let response: Response;
    try {
      response = await fetch(`${API_BASE}${path}`, {
        signal: AbortSignal.timeout(20_000),
        method: options.body === undefined ? "GET" : "POST",
        headers: {
          ...(options.body === undefined ? {} : { "content-type": "application/json" }),
          ...(options.token ? { authorization: `Bearer ${options.token}` } : {}),
        },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch (error) {
      // Transport failure: dropped connection, timeout, DNS — retry.
      lastError = error;
      continue;
    }
    const value = await response.json().catch(() => ({})) as { detail?: unknown } & T;
    if (response.ok) return value;
    const detail = typeof value.detail === "string" ? value.detail : "Не удалось связаться с платёжным сервером.";
    if (retryable(response.status)) {
      // Server error / rate limit may pass on its own — retry.
      lastError = new Error(detail);
      continue;
    }
    // A 4xx business rejection (bad credentials, expired token) will not fix
    // itself by retrying: surface it immediately.
    throw new Error(detail);
  }
  throw lastError instanceof Error ? lastError : new Error("Не удалось связаться с платёжным сервером.");
}

export const payments = {
  providers: () => api<{ github: boolean; google: boolean }>("/v1/auth/providers"),
  register: (username: string, password: string) => api<{ access_token: string; account: Account }>("/v1/auth/register", { body: { username, password } }),
  login: (username: string, password: string) => api<{ access_token: string; account: Account }>("/v1/auth/login", { body: { username, password } }),
  oauthStart: (provider: "github" | "google") => api<{ authorization_url: string; poll_token: string }>("/v1/auth/oauth/start", { body: { provider } }),
  oauthStatus: (pollToken: string) => api<{ status: "pending" | "success" | "error"; code: string | null; error: string | null }>("/v1/auth/oauth/status", { body: { poll_token: pollToken } }),
  oauthRedeem: (code: string) => api<{ access_token: string; account: Account }>("/v1/auth/oauth/redeem", { body: { code } }),
  account: (token: string) => api<Account>("/v1/me", { token }),
  logout: (token: string) => api<void>("/v1/auth/logout", { token, body: {} }),
  topup: (token: string, amountRub: string) => api<{ payment: Payment }>("/v1/payments/topup", { token, body: { type: "balance_topup", amount_rub: amountRub } }),
  buyPro: (token: string) => api<{ payment: Payment }>("/v1/payments/pro", { token, body: { type: "pro" } }),
  buyProFromBalance: (token: string) => api<{ account: Account }>("/v1/payments/pro/balance", { token, body: {} }),
  status: (token: string, id: string) => api<{ payment: Payment; account: Account }>(`/v1/payments/${encodeURIComponent(id)}`, { token }),
};

export const rubles = (minor: number) => new Intl.NumberFormat("ru-RU", {
  style: "currency", currency: "RUB", maximumFractionDigits: minor % 100 ? 2 : 0,
}).format(minor / 100);

export function parseAmount(value: string): number | null {
  if (!/^\d{1,6}([.,]\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.replace(",", ".").split(".");
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return amount >= 10_000 && amount <= 10_000_000 ? amount : null;
}

export function formatExpiry(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
