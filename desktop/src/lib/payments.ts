export type PaymentType = "balance_topup" | "pro";
export type PaymentStatus = "pending" | "paid" | "failed" | "expired";

export interface Payment {
  id: string;
  type: PaymentType;
  amount_minor: number;
  status: PaymentStatus;
  created_at: string;
  paid_at: string | null;
  expires_at: string | null;
  failure_reason: string | null;
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
  const response = await fetch(`${API_BASE}${path}`, {
    method: options.body === undefined ? "GET" : "POST",
    headers: {
      ...(options.body === undefined ? {} : { "content-type": "application/json" }),
      ...(options.token ? { authorization: `Bearer ${options.token}` } : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const value = await response.json().catch(() => ({})) as { detail?: unknown } & T;
  if (!response.ok) {
    const detail = typeof value.detail === "string" ? value.detail : "Не удалось связаться с платёжным сервером.";
    throw new Error(detail);
  }
  return value;
}

export const payments = {
  register: (username: string, password: string) => api<{ access_token: string; account: Account }>("/v1/auth/register", { body: { username, password } }),
  login: (username: string, password: string) => api<{ access_token: string; account: Account }>("/v1/auth/login", { body: { username, password } }),
  account: (token: string) => api<Account>("/v1/me", { token }),
  logout: (token: string) => api<void>("/v1/auth/logout", { token, body: {} }),
  topup: (token: string, amountRub: string) => api<{ payment: Payment }>("/v1/payments/topup", { token, body: { type: "balance_topup", amount_rub: amountRub } }),
  buyPro: (token: string) => api<{ payment: Payment }>("/v1/payments/pro", { token, body: { type: "pro" } }),
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
