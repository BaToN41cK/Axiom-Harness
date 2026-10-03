import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Clock, Copy, Crown, CreditCard, ExternalLink, Loader2, LogOut, RefreshCw, ShieldCheck, Sparkles, Wallet, X } from "lucide-react";
import { axiomUsd, formatExpiry, parseAmount, rubles, rubMinorToAxiomUsdMinor } from "../lib/payments";
import type { Payment } from "../lib/payments";
import type { usePayments } from "../hooks/usePayments";
import { useLocale } from "../lib/locale";
import { pluralKey } from "../lib/i18n";
import "../styles/account.css";

type Payments = ReturnType<typeof usePayments>;

const PRO_PRICE_RUB_MINOR = 99_000;
const PRO_PRICE_USD_MINOR = 990;
const PRO_DAYS = 30;
const PRESETS = [100, 250, 500, 1000];
/** Facts guaranteed by payment-backend — no marketing promises. */
const PRO_FACTS = [
  "ui.acct.fact.days",
  "ui.acct.fact.renew",
  "ui.acct.fact.pay",
  "ui.acct.fact.account",
];

function paymentMessage(payment: Payment, t: (key: string) => string): string {
  if (payment.status === "paid") return payment.type === "pro" ? t("ui.acct.pro_activated") : t("ui.acct.balance_credited");
  if (payment.status === "expired") return t("ui.acct.payment_expired");
  if (payment.status === "failed") {
    if (payment.failure_reason === "below_minimum") return t("ui.acct.below_minimum");
    if (payment.failure_reason === "late_payment") return t("ui.acct.late_payment");
    if (payment.failure_reason === "order_not_pending") return t("ui.acct.order_processed");
    return t("ui.acct.amount_mismatch");
  }
  return t("ui.acct.waiting_payment");
}

function daysLeft(expires: string | null): number | null {
  if (!expires) return null;
  const t = new Date(expires).getTime();
  if (Number.isNaN(t)) return null;
  return Math.max(0, (t - Date.now()) / 86_400_000);
}

function useCountdown(target: string | null): string | null {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!target) return;
    const id = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [target]);
  if (!target) return null;
  const left = Math.max(0, Math.floor((new Date(target).getTime() - Date.now()) / 1000));
  if (!Number.isFinite(left)) return null;
  const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

export default function AccountView({
  s, amount, setAmount, qr, onOpenPayment, linkError,
}: {
  s: Payments;
  amount: string;
  setAmount: (value: string) => void;
  qr: boolean[][] | null;
  onOpenPayment: () => void;
  linkError: string | null;
}) {
  const account = s.account!;
  const { t, locale } = useLocale();
  const topupRef = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  const amountMinor = parseAmount(amount);
  const pending = s.payment?.status === "pending";
  const pro = account.pro_active;
  const left = daysLeft(account.pro_expires_at);
  const proFraction = pro && left !== null ? Math.min(1, left / PRO_DAYS) : 0;
  const shortfall = Math.max(0, PRO_PRICE_USD_MINOR - account.balance_minor);
  const initials = (account.username || "AX").slice(0, 2).toUpperCase();
  const countdown = useCountdown(pending ? s.payment?.expires_at ?? null : null);
  const disabled = s.busy || s.active || !account.payments_available;

  const copyLink = async () => {
    const url = s.payment?.payment_url;
    if (!url) return;
    try { await navigator.clipboard.writeText(url); setCopied(true); window.setTimeout(() => setCopied(false), 1400); } catch { /* blocked */ }
  };

  return (
    <div className="acct">
      {/* ---------------------------------------------------------- profile */}
      <section className={"acct-hero" + (pro ? " is-pro" : "")}>
        <div className="acct-profile">
          <div className="acct-avatar" aria-hidden="true">{initials}</div>
          <div className="acct-id">
            <div className="acct-name">
              {account.username}
              <span className={"acct-plan" + (pro ? " pro" : "")}>{pro ? <><Crown size={11} /> PRO</> : "FREE"}</span>
            </div>
            <div className="acct-sub"><ShieldCheck size={12} /> {t("ui.acct.session")}</div>
          </div>
          <div className="acct-hero-actions">
            <button className="icon-btn" title={t("ui.common.refresh")} aria-label={t("ui.acct.refresh_aria")} onClick={() => void s.refresh()}><RefreshCw size={14} /></button>
            <button className="btn ghost acct-logout" onClick={s.signOut}><LogOut size={13} /> {t("ui.acct.logout")}</button>
          </div>
        </div>
        <div className="acct-balance">
          <span className="acct-balance-label"><Wallet size={13} /> {t("ui.acct.balance")}</span>
          <strong className="acct-balance-value">{axiomUsd(account.balance_minor)}</strong>
          <span className="acct-balance-unit">{t("ui.acct.balance_unit")}</span>
          <button className="btn acct-balance-add" onClick={() => topupRef.current?.focus()}>{t("ui.acct.topup")} <ArrowRight size={13} /></button>
        </div>
      </section>

      <div className="acct-grid">
        {/* ------------------------------------------------------------ PRO */}
        <section className={"acct-card acct-pro" + (pro ? " active" : "")}>
          <div className="acct-card-head">
            <span className="acct-pro-icon"><Crown size={16} /></span>
            <div>
              <span className="acct-kicker">{t("ui.acct.subscription")}</span>
              <h3>AXIOM PRO</h3>
            </div>
            <div className="acct-price"><strong>{rubles(PRO_PRICE_RUB_MINOR)}</strong><span>{t("ui.acct.days_left", { n: String(PRO_DAYS) })}</span></div>
          </div>

          {pro && left !== null ? (
            <div className="acct-pro-status">
              <div className="acct-pro-meter"><span style={{ width: `${Math.max(3, proFraction * 100)}%` }} /></div>
              <div className="acct-pro-meta">
                <span><b>{Math.floor(left)}</b> {t("ui.acct.left", { unit: t(`ui.acct.day.${pluralKey(Math.floor(left), locale) === "other" ? "few" : pluralKey(Math.floor(left), locale)}`) })}</span>
                <span>{t("ui.acct.until", { expiry: formatExpiry(account.pro_expires_at) })}</span>
              </div>
            </div>
          ) : (
            <p className="acct-muted">{t("ui.acct.not_active")}</p>
          )}

          <ul className="acct-facts">
            {PRO_FACTS.map((fact) => <li key={fact}><Check size={12} strokeWidth={2.6} />{t(fact)}</li>)}
          </ul>

          <div className="acct-actions">
            <button className="btn primary acct-gold" disabled={disabled} onClick={() => void s.buyPro()}>
              {s.busy ? <Loader2 size={14} className="spin" /> : <CreditCard size={14} />}
              {pro ? t("ui.acct.renew") : t("ui.acct.subscribe")} · {rubles(PRO_PRICE_RUB_MINOR)}
            </button>
            <button
              className="btn"
              disabled={s.busy || s.active || shortfall > 0}
              title={shortfall > 0 ? t("ui.acct.shortage", { amount: axiomUsd(shortfall) }) : undefined}
              onClick={() => void s.buyProFromBalance()}
            >
              <Wallet size={14} /> {t("ui.acct.from_balance", { amount: axiomUsd(PRO_PRICE_USD_MINOR) })}
            </button>
          </div>
          {shortfall > 0 && <span className="acct-hint">{t("ui.acct.shortage_hint", { amount: axiomUsd(shortfall) })}</span>}
        </section>

        {/* --------------------------------------------------------- top-up */}
        <section className="acct-card acct-topup">
          <div className="acct-card-head">
            <span className="acct-topup-icon"><Sparkles size={16} /></span>
            <div>
              <span className="acct-kicker">{t("ui.acct.balance")}</span>
              <h3>{t("ui.acct.topup")}</h3>
            </div>
          </div>
          <div className="acct-presets" role="group" aria-label={t("ui.acct.quick_topup_aria")}>
            {PRESETS.map((value) => {
              const selected = amountMinor === value * 100;
              return (
                <button key={value} className={"acct-preset" + (selected ? " selected" : "")} disabled={s.active} aria-pressed={selected} onClick={() => setAmount(String(value))}>
                  <strong>{rubles(value * 100)}</strong>
                  <span>{axiomUsd(rubMinorToAxiomUsdMinor(value * 100))}</span>
                </button>
              );
            })}
          </div>
          <label className={"acct-amount" + (amountMinor === null ? " invalid" : "")}>
            <span>{t("ui.acct.custom_amount")}</span>
            <input ref={topupRef} inputMode="decimal" value={amount} disabled={s.active} aria-invalid={amountMinor === null} onChange={(e) => setAmount(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && amountMinor && !disabled) void s.createTopup((amountMinor / 100).toFixed(2)); }} />
            <em>₽</em>
          </label>
          <div className="acct-summary">
            <div><span>{t("ui.acct.you_pay")}</span><b>{amountMinor === null ? "—" : rubles(amountMinor)}</b></div>
            <ArrowRight size={14} />
            <div><span>{t("ui.acct.you_get")}</span><b className="good">{amountMinor === null ? "—" : axiomUsd(rubMinorToAxiomUsdMinor(amountMinor))}</b></div>
          </div>
          {amountMinor === null && <span className="acct-hint bad">{t("ui.acct.amount_range")}</span>}
          <button className="btn primary" disabled={disabled || !amountMinor} onClick={() => amountMinor && void s.createTopup((amountMinor / 100).toFixed(2))}>
            {s.busy ? <Loader2 size={14} className="spin" /> : <CreditCard size={14} />}
            {amountMinor ? t("ui.acct.topup_amount", { amount: rubles(amountMinor) }) : t("ui.acct.topup")}
          </button>
          <span className="acct-hint">{t("ui.acct.fixed_rate")}</span>
        </section>
      </div>

      {account.payments_message && <div className="acct-banner warn">{account.payments_message}</div>}

      {/* -------------------------------------------------------- payment */}
      {s.payment && (
        <section className={"acct-card acct-payment status-" + s.payment.status} role="status">
          <div className="acct-pay-head">
            <span className="acct-pay-icon">
              {s.payment.status === "paid" ? <Check size={16} /> : s.payment.status === "pending" ? <Loader2 size={16} className="spin" /> : <X size={16} />}
            </span>
            <div>
              <strong>{paymentMessage(s.payment, t)}</strong>
              <span>{s.payment.type === "pro" ? `${t("ui.acct.pro_type")} · ${rubles(PRO_PRICE_RUB_MINOR)}` : `${t("ui.acct.topup_type")} · ${rubles(s.payment.amount_minor)}`}</span>
            </div>
            {pending && countdown && <span className="acct-timer"><Clock size={12} /> {countdown}</span>}
          </div>

          <ol className="acct-steps">
            {[t("ui.acct.step.created"), t("ui.acct.step.payment"), t("ui.acct.step.confirmed")].map((label, index) => {
              const reached = s.payment!.status === "paid" ? 3 : 1;
              const state = index < reached ? "done" : index === reached && pending ? "now" : "todo";
              return <li key={label} className={state}><span>{state === "done" ? <Check size={11} strokeWidth={3} /> : index + 1}</span>{label}</li>;
            })}
          </ol>

          {s.payment.status === "paid" && (
            <p className="acct-muted">
              {s.payment.type === "pro"
                ? t("ui.acct.pro_until", { expiry: formatExpiry(account.pro_expires_at) })
                : t("ui.acct.confirmed", { received: rubles(s.payment.received_rub_minor ?? s.payment.amount_minor), credited: axiomUsd(s.payment.credited_axiom_usd_minor ?? rubMinorToAxiomUsdMinor(s.payment.amount_minor)) })}
            </p>
          )}

          {pending && (
            <div className="acct-pay-body">
              {qr && (
                <svg className="acct-qr" viewBox="0 0 65 65" role="img" aria-label={t("ui.acct.qr_aria")} shapeRendering="crispEdges">
                  <rect width="65" height="65" fill="white" />
                  <path fill="black" d={qr.flatMap((row, y) => row.map((value, x) => (value ? `M${x + 4},${y + 4}h1v1h-1z` : ""))).join("")} />
                </svg>
              )}
              <div className="acct-pay-actions">
                <p className="acct-muted">{t("ui.acct.scan")}</p>
                <button className="btn primary" disabled={!s.payment.payment_url} onClick={onOpenPayment}><ExternalLink size={14} /> {t("ui.acct.open_payment")}</button>
                <button className="btn ghost" disabled={!s.payment.payment_url} onClick={() => void copyLink()}>{copied ? <Check size={13} /> : <Copy size={13} />} {copied ? t("ui.acct.link_copied") : t("ui.acct.copy_link")}</button>
                <span className="acct-hint">{t("ui.acct.webhook_note")}</span>
              </div>
            </div>
          )}
        </section>
      )}

      {(s.error || linkError) && <div className="acct-banner bad" role="alert">{s.error || linkError}</div>}
    </div>
  );
}
