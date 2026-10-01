import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Clock, Copy, Crown, CreditCard, ExternalLink, Loader2, LogOut, RefreshCw, ShieldCheck, Sparkles, Wallet, X } from "lucide-react";
import { axiomUsd, formatExpiry, parseAmount, rubles, rubMinorToAxiomUsdMinor } from "../lib/payments";
import type { Payment } from "../lib/payments";
import type { usePayments } from "../hooks/usePayments";
import "../styles/account.css";

type Payments = ReturnType<typeof usePayments>;

const PRO_PRICE_RUB_MINOR = 99_000;
const PRO_PRICE_USD_MINOR = 990;
const PRO_DAYS = 30;
const PRESETS = [100, 250, 500, 1000];
/** Facts guaranteed by payment-backend — no marketing promises. */
const PRO_FACTS = [
  "30 дней с момента оплаты",
  "Продление заранее добавляет 30 дней к текущей дате окончания",
  "Оплата картой / кошельком ЮMoney или AXIOM-кредитами",
  "Один аккаунт для desktop-приложения и терминала (TUI)",
];

function paymentMessage(payment: Payment): string {
  if (payment.status === "paid") return payment.type === "pro" ? "AXIOM PRO активирован" : "Баланс пополнен";
  if (payment.status === "expired") return "Платёж истёк";
  if (payment.status === "failed") {
    if (payment.failure_reason === "below_minimum") return "Поступило меньше 100 ₽. Баланс не изменён; платёж записан для сверки.";
    if (payment.failure_reason === "late_payment") return "Платёж поступил после срока заказа. Свяжитесь с поддержкой для сверки.";
    if (payment.failure_reason === "order_not_pending") return "Заказ уже обработан. Баланс не изменён повторно.";
    return "Сумма не совпала с заказом. Баланс и AXIOM PRO не изменены.";
  }
  return "Ожидание оплаты";
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
            <div className="acct-sub"><ShieldCheck size={12} /> Сессия хранится на этом устройстве</div>
          </div>
          <div className="acct-hero-actions">
            <button className="icon-btn" title="Обновить" aria-label="Обновить данные аккаунта" onClick={() => void s.refresh()}><RefreshCw size={14} /></button>
            <button className="btn ghost acct-logout" onClick={s.signOut}><LogOut size={13} /> Выйти</button>
          </div>
        </div>
        <div className="acct-balance">
          <span className="acct-balance-label"><Wallet size={13} /> Баланс</span>
          <strong className="acct-balance-value">{axiomUsd(account.balance_minor)}</strong>
          <span className="acct-balance-unit">AXIOM USD-кредиты · курс 100 ₽ = $1.00</span>
          <button className="btn acct-balance-add" onClick={() => topupRef.current?.focus()}>Пополнить <ArrowRight size={13} /></button>
        </div>
      </section>

      <div className="acct-grid">
        {/* ------------------------------------------------------------ PRO */}
        <section className={"acct-card acct-pro" + (pro ? " active" : "")}>
          <div className="acct-card-head">
            <span className="acct-pro-icon"><Crown size={16} /></span>
            <div>
              <span className="acct-kicker">Подписка</span>
              <h3>AXIOM PRO</h3>
            </div>
            <div className="acct-price"><strong>{rubles(PRO_PRICE_RUB_MINOR)}</strong><span>/ {PRO_DAYS} дней</span></div>
          </div>

          {pro && left !== null ? (
            <div className="acct-pro-status">
              <div className="acct-pro-meter"><span style={{ width: `${Math.max(3, proFraction * 100)}%` }} /></div>
              <div className="acct-pro-meta">
                <span><b>{Math.floor(left)}</b> {plural(Math.floor(left), "день", "дня", "дней")} осталось</span>
                <span>до {formatExpiry(account.pro_expires_at)}</span>
              </div>
            </div>
          ) : (
            <p className="acct-muted">Подписка не активна. После оплаты включится автоматически.</p>
          )}

          <ul className="acct-facts">
            {PRO_FACTS.map((fact) => <li key={fact}><Check size={12} strokeWidth={2.6} />{fact}</li>)}
          </ul>

          <div className="acct-actions">
            <button className="btn primary acct-gold" disabled={disabled} onClick={() => void s.buyPro()}>
              {s.busy ? <Loader2 size={14} className="spin" /> : <CreditCard size={14} />}
              {pro ? "Продлить" : "Оформить"} · {rubles(PRO_PRICE_RUB_MINOR)}
            </button>
            <button
              className="btn"
              disabled={s.busy || s.active || shortfall > 0}
              title={shortfall > 0 ? `Не хватает ${axiomUsd(shortfall)}` : undefined}
              onClick={() => void s.buyProFromBalance()}
            >
              <Wallet size={14} /> {axiomUsd(PRO_PRICE_USD_MINOR)} с баланса
            </button>
          </div>
          {shortfall > 0 && <span className="acct-hint">Для оплаты с баланса не хватает {axiomUsd(shortfall)}.</span>}
        </section>

        {/* --------------------------------------------------------- top-up */}
        <section className="acct-card acct-topup">
          <div className="acct-card-head">
            <span className="acct-topup-icon"><Sparkles size={16} /></span>
            <div>
              <span className="acct-kicker">Баланс</span>
              <h3>Пополнить</h3>
            </div>
          </div>
          <div className="acct-presets" role="group" aria-label="Быстрая сумма пополнения">
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
            <span>Своя сумма</span>
            <input ref={topupRef} inputMode="decimal" value={amount} disabled={s.active} aria-invalid={amountMinor === null} onChange={(e) => setAmount(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && amountMinor && !disabled) void s.createTopup((amountMinor / 100).toFixed(2)); }} />
            <em>₽</em>
          </label>
          <div className="acct-summary">
            <div><span>Вы платите</span><b>{amountMinor === null ? "—" : rubles(amountMinor)}</b></div>
            <ArrowRight size={14} />
            <div><span>Получите</span><b className="good">{amountMinor === null ? "—" : axiomUsd(rubMinorToAxiomUsdMinor(amountMinor))}</b></div>
          </div>
          {amountMinor === null && <span className="acct-hint bad">Введите сумму от 100 до 100 000 ₽ (до копеек).</span>}
          <button className="btn primary" disabled={disabled || !amountMinor} onClick={() => amountMinor && void s.createTopup((amountMinor / 100).toFixed(2))}>
            {s.busy ? <Loader2 size={14} className="spin" /> : <CreditCard size={14} />}
            {amountMinor ? `Пополнить на ${rubles(amountMinor)}` : "Пополнить"}
          </button>
          <span className="acct-hint">Фиксированный курс AXIOM, а не курс обмена валют.</span>
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
              <strong>{paymentMessage(s.payment)}</strong>
              <span>{s.payment.type === "pro" ? `AXIOM PRO · ${rubles(PRO_PRICE_RUB_MINOR)}` : `Пополнение · ${rubles(s.payment.amount_minor)}`}</span>
            </div>
            {pending && countdown && <span className="acct-timer"><Clock size={12} /> {countdown}</span>}
          </div>

          <ol className="acct-steps">
            {["Заказ создан", "Оплата на странице ЮMoney", "Подтверждено сервером"].map((label, index) => {
              const reached = s.payment!.status === "paid" ? 3 : 1;
              const state = index < reached ? "done" : index === reached && pending ? "now" : "todo";
              return <li key={label} className={state}><span>{state === "done" ? <Check size={11} strokeWidth={3} /> : index + 1}</span>{label}</li>;
            })}
          </ol>

          {s.payment.status === "paid" && (
            <p className="acct-muted">
              {s.payment.type === "pro"
                ? `Подписка активна до ${formatExpiry(account.pro_expires_at)}.`
                : `Подтверждено ${rubles(s.payment.received_rub_minor ?? s.payment.amount_minor)} · зачислено ${axiomUsd(s.payment.credited_axiom_usd_minor ?? rubMinorToAxiomUsdMinor(s.payment.amount_minor))}.`}
            </p>
          )}

          {pending && (
            <div className="acct-pay-body">
              {qr && (
                <svg className="acct-qr" viewBox="0 0 65 65" role="img" aria-label="QR-код страницы оплаты ЮMoney" shapeRendering="crispEdges">
                  <rect width="65" height="65" fill="white" />
                  <path fill="black" d={qr.flatMap((row, y) => row.map((value, x) => (value ? `M${x + 4},${y + 4}h1v1h-1z` : ""))).join("")} />
                </svg>
              )}
              <div className="acct-pay-actions">
                <p className="acct-muted">Отсканируйте QR-код телефоном или откройте страницу оплаты в браузере.</p>
                <button className="btn primary" disabled={!s.payment.payment_url} onClick={onOpenPayment}><ExternalLink size={14} /> Открыть страницу оплаты</button>
                <button className="btn ghost" disabled={!s.payment.payment_url} onClick={() => void copyLink()}>{copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Ссылка скопирована" : "Скопировать ссылку"}</button>
                <span className="acct-hint">Баланс изменится только после подписанного уведомления ЮMoney. Возврат из браузера сам по себе оплату не подтверждает.</span>
              </div>
            </div>
          )}
        </section>
      )}

      {(s.error || linkError) && <div className="acct-banner bad" role="alert">{s.error || linkError}</div>}
    </div>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
