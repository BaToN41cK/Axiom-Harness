import { request } from "../bridge";

export interface Payment {
  id: string;
  amount_minor: number;
  currency: "RUB";
  status: "creating" | "pending" | "paid" | "cancelled" | "expired" | "error";
  payment_url: string | null;
  created_at: number;
  paid_at: number | null;
}
export interface Wallet {
  balance_minor: number;
  available: boolean;
  message: string | null;
  automatic_confirmation: boolean;
  payment: Payment | null;
}
export interface PaymentReply { payment: Payment; balance_minor: number }

export const payments = {
  wallet: () => request<Wallet>("payment_wallet"),
  create: (amount: number, key: string) => request<PaymentReply>("payment_create", { amount_minor: amount, request_key: key }),
  status: (id: string) => request<PaymentReply>("payment_status", { id }),
  cancel: (id: string) => request<PaymentReply>("payment_cancel", { id }),
};
export const rubles = (minor: number) => new Intl.NumberFormat("ru-RU", {
  style: "currency", currency: "RUB", maximumFractionDigits: minor % 100 ? 2 : 0,
}).format(minor / 100);
export function parseAmount(value: string): number | null {
  if (!/^\d{1,6}([.,]\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.replace(",", ".").split(".");
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return amount >= 10000 && amount <= 10000000 ? amount : null;
}