import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { createPortal } from "react-dom";
import { Check, Crown, ExternalLink, Github, Loader2, Plus, Wallet, X } from "lucide-react";
import { openExternal } from "../bridge";
import Presence from "./Presence";
import { usePayments } from "../hooks/usePayments";
import { axiomUsd, formatExpiry, parseAmount, paymentBackendConfigured, paymentToken, rubles, rubMinorToAxiomUsdMinor } from "../lib/payments";
import type { Payment } from "../lib/payments";
import { paymentQr } from "../lib/paymentQr";
import "../styles/payments.css";

function paymentMessage(payment: Payment | null): string {
  if (!payment) return "";
  if (payment.status === "paid") return payment.type === "pro" ? "AXIOM PRO активирован" : "Баланс обновлён";
  if (payment.status === "expired") return "Платёж истёк";
  if (payment.status === "failed") {
    if (payment.failure_reason === "below_minimum") return "Поступило меньше 100 ₽. Баланс не изменён; платёж записан для сверки.";
    if (payment.failure_reason === "late_payment") return "Платёж поступил после срока заказа. Свяжитесь с поддержкой для сверки.";
    if (payment.failure_reason === "order_not_pending") return "Заказ уже обработан. Баланс не изменён повторно.";
    return "Сумма не совпала с заказом. Баланс и AXIOM PRO не изменены.";
  }
  return "Ожидание оплаты";
}

export default function Balance() {
  const s = usePayments();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("300");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [createAccount, setCreateAccount] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const amountMinor = parseAmount(amount);
  const qr = useMemo(() => {
    if (s.payment?.status !== "pending" || !s.payment.payment_url) return null;
    try { return paymentQr(s.payment.payment_url); } catch { return null; }
  }, [s.payment?.id, s.payment?.status, s.payment?.payment_url]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const submitAuth = (event: FormEvent) => {
    event.preventDefault();
    void s.authenticate(username, password, createAccount);
  };
  const openPayment = async () => {
    const url = s.payment?.payment_url;
    if (!url || !url.startsWith("https://")) return;
    try { setLinkError(null); await openExternal(url); }
    catch { setLinkError("Не удалось открыть браузер. Отсканируйте QR-код или попробуйте ещё раз."); }
  };
  const createTopup = () => {
    if (!amountMinor || s.active || !s.account?.payments_available) return;
    void s.createTopup((amountMinor / 100).toFixed(2));
  };
  const createPro = () => {
    if (!s.active && s.account?.payments_available) void s.buyPro();
  };
  const createProFromBalance = () => {
    if (!s.active && s.account && s.account.balance_minor >= 990) void s.buyProFromBalance();
  };
  const balanceLabel = s.account ? axiomUsd(s.account.balance_minor) : "—";
  const topupUsdLabel = amountMinor === null ? "—" : axiomUsd(rubMinorToAxiomUsdMinor(amountMinor));
  const pending = s.payment?.status === "pending";

  return <>
    <button
      className={"balance-pill" + (s.account?.pro_active ? " balance-pro" : "")}
      title={`Баланс ${balanceLabel} AXIOM USD-кредитов · AXIOM PRO`}
      aria-label={`Баланс ${balanceLabel} AXIOM USD-кредитов. Открыть баланс и AXIOM PRO`}
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={() => { setOpen(true); if (paymentToken.get()) void s.refresh(); }}
    >
      <Wallet size={14} /><span className="balance-label">Баланс</span><strong>{balanceLabel}</strong>
      {s.account?.pro_active && <Crown size={13} className="balance-crown" aria-label="AXIOM PRO" />}
      <span className="balance-plus"><Plus size={13} /></span>
      {pending && <span className="balance-pending" aria-label="Ожидание оплаты" />}
    </button>
    {createPortal(<Presence open={open}>
      <div className="modal-backdrop payment-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
        <section className="modal payment-dialog" role="dialog" aria-modal="true" aria-labelledby="payment-title">
          <div className="modal-head">
            <h2 id="payment-title">Баланс и AXIOM PRO</h2>
            <button className="icon-btn" aria-label="Закрыть платежи" onClick={() => setOpen(false)}><X size={16} /></button>
          </div>
          {!paymentBackendConfigured ? <div className="modal-body">
            <p className="payment-note payment-unavailable">Платёжный сервер не настроен в этой сборке AXIOM.</p>
          </div> : !s.account ? <div className="modal-body">
            <p className="payment-note">Баланс и подписка привязаны к аккаунту AXIOM. Создайте аккаунт или войдите, чтобы продолжить.</p>
            <form className="payment-auth" onSubmit={submitAuth}>
              <label className="field"><span className="field-label">Имя пользователя</span>
                <input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required minLength={3} maxLength={48} />
              </label>
              <label className="field"><span className="field-label">Пароль</span>
                <input type="password" autoComplete={createAccount ? "new-password" : "current-password"} value={password} onChange={(event) => setPassword(event.target.value)} required minLength={12} maxLength={256} />
              </label>
              {createAccount && <span className="payment-note">Пароль должен содержать не менее 12 символов. Сохраните его: восстановление пароля пока не подключено.</span>}
              <button className="btn primary" disabled={s.busy}>
                {s.busy ? <><Loader2 size={14} className="spin" /> Подождите…</> : createAccount ? "Создать аккаунт" : "Войти"}
              </button>
            </form>
            <button className="payment-text-button" onClick={() => setCreateAccount(!createAccount)}>
              {createAccount ? "Уже есть аккаунт? Войти" : "Создать аккаунт AXIOM"}
            </button>
            <div className="payment-auth-divider"><span>или продолжить через</span></div>
            <div className="payment-oauth-buttons">
              <button className="btn payment-oauth" disabled={s.busy || !s.providers.github} onClick={() => void s.authenticateWithProvider("github")}><Github size={15} /> GitHub</button>
              <button className="btn payment-oauth" disabled={s.busy || !s.providers.google} onClick={() => void s.authenticateWithProvider("google")}><strong className="google-mark">G</strong> Google</button>
            </div>
            {(!s.providers.github || !s.providers.google) && <p className="payment-note">Недоступные способы входа ещё не настроены на сервере.</p>}
            {s.oauthPending && <div role="status" className="payment-note">Завершите вход в открытом браузере. Не переходите по ссылкам входа от других людей.
              <button className="payment-text-button" onClick={s.cancelOAuth}>Отменить ожидание</button>
            </div>}
          </div> : <div className="modal-body">
            <div className="payment-balance">
              <span>Внутренние AXIOM USD-кредиты</span><strong>{balanceLabel}</strong>
              <span className="payment-account">Аккаунт: {s.account.username}</span>
            </div>
            <section className="payment-section">
              <div className="payment-section-head"><div><span className="payment-kicker">ПОДПИСКА</span><h3>AXIOM PRO</h3></div><strong className="payment-pro-price">990 ₽</strong></div>
              <p className="payment-note">30 дней. {s.account.pro_active ? `Активна до ${formatExpiry(s.account.pro_expires_at)}.` : "После оплаты подписка включится автоматически."}</p>
              <button className="btn primary" disabled={s.busy || s.active || !s.account.payments_available} onClick={createPro}>
                {s.busy ? "Создание…" : s.account.pro_active ? "Продлить AXIOM PRO" : "Купить PRO · 990 ₽"}
              </button>
              <button className="btn" disabled={s.busy || s.active || s.account.balance_minor < 990} onClick={createProFromBalance}>
                {s.account.pro_active ? "Продлить PRO за $9.90 AXIOM" : "Купить PRO за $9.90 AXIOM"}
              </button>
            </section>
            <section className="payment-section">
              <div className="payment-section-head"><div><span className="payment-kicker">БАЛАНС</span><h3>Пополнить баланс</h3></div></div>
              <div className="payment-presets" role="group" aria-label="Быстрая сумма пополнения">
                {[100, 250, 500, 1000].map((value) => <button key={value} className={"btn" + (amountMinor === value * 100 ? " selected" : "")} disabled={s.active} aria-pressed={amountMinor === value * 100} onClick={() => setAmount(String(value))}>{rubles(value * 100)}</button>)}
              </div>
              <label className="field"><span className="field-label">Сумма оплаты, ₽</span>
                <input inputMode="decimal" value={amount} disabled={s.active} aria-describedby="payment-range" aria-invalid={amountMinor === null} onChange={(event) => setAmount(event.target.value)} />
              </label>
              <span className="payment-note" id="payment-range">Вы платите RUB. Фиксированный курс AXIOM: 100 ₽ = $1.00 внутреннего баланса, не курс обмена валют.</span>
              <div className="payment-note">Вы получите: <strong>{topupUsdLabel} AXIOM USD-кредитов</strong></div>
              <button className="btn primary" disabled={s.busy || s.active || !amountMinor || !s.account.payments_available} onClick={createTopup}>
                {s.busy ? "Создание…" : `Пополнить на ${amount} ₽`}
              </button>
            </section>
            {s.account.payments_message && <p className="payment-note payment-unavailable">{s.account.payments_message}</p>}
            {s.payment && <section className={"payment-result" + (s.payment.status === "paid" ? " payment-success" : "")} role="status">
              {s.payment.status === "paid" ? <Check size={20} /> : s.payment.status === "pending" ? <Loader2 size={16} className="spin" /> : null}
              <strong>{paymentMessage(s.payment)}</strong>
              {s.payment.status === "paid" && <span>{s.payment.type === "pro" ? `Подписка до ${formatExpiry(s.account.pro_expires_at)}` : `Подтверждено ${rubles(s.payment.received_rub_minor ?? s.payment.amount_minor)} · зачислено ${axiomUsd(s.payment.credited_axiom_usd_minor ?? rubMinorToAxiomUsdMinor(s.payment.amount_minor))} AXIOM USD-кредитов`}</span>}
              {pending && <>
                <span>{s.payment.type === "pro" ? "AXIOM PRO · 990 ₽" : `Зачисление · ${rubles(s.payment.amount_minor)}`}</span>
                {qr && <svg className="payment-qr" viewBox="0 0 65 65" role="img" aria-label="QR-код страницы оплаты YooMoney" shapeRendering="crispEdges">
                  <rect width="65" height="65" fill="white" />
                  <path fill="black" d={qr.flatMap((row, y) => row.map((value, x) => value ? `M${x + 4},${y + 4}h1v1h-1z` : "")).join("")} />
                </svg>}
                <button className="btn payment-open" disabled={!s.payment.payment_url} onClick={() => void openPayment()}><ExternalLink size={14} />Открыть страницу оплаты</button>
                <span className="payment-note">Баланс обновится после проверки подписанного уведомления ЮMoney. Возврат из браузера сам по себе не подтверждает оплату.</span>
              </>}
            </section>}
            {(s.error || linkError) && <div className="payment-error" role="alert">{s.error || linkError}</div>}
            <div className="payment-account-row"><span>Сессия аккаунта хранится на этом устройстве.</span><button className="payment-text-button" onClick={s.signOut}>Выйти</button></div>
          </div>}
          {!s.account && s.error && <div className="payment-error payment-auth-error" role="alert">{s.error}</div>}
        </section>
      </div>
    </Presence>, document.body)}
  </>;
}
