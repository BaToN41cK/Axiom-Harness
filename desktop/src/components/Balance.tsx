import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Clock3, ExternalLink, Loader2, Plus, Wallet as WalletIcon, X } from "lucide-react";
import { createPortal } from "react-dom";
import { openExternal } from "../bridge";
import { usePayments } from "../hooks/usePayments";
import { parseAmount, rubles } from "../lib/payments";
import { paymentQr } from "../lib/paymentQr";
import Presence from "./Presence";
import "../styles/payments.css";

type Store = ReturnType<typeof usePayments>;

function PaymentDialog({ store: s, onClose }: { store: Store; onClose: () => void }) {
  const [amount, setAmount] = useState("300");
  const [linkError, setLinkError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current!;
    node.focus();
    const key = (e: KeyboardEvent) => {
      if (node.closest("[inert]")) return;
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); close.current(); }
      if (e.key === "Tab") {
        const items = Array.from(node.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled])"));
        const first = items[0], last = items[items.length - 1];
        if (!node.contains(document.activeElement) || document.activeElement === node ||
          (e.shiftKey && document.activeElement === first) || (!e.shiftKey && document.activeElement === last)) {
          e.preventDefault(); (e.shiftKey ? last : first)?.focus();
        }
      }
    };
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("keydown", key, true); previous?.focus(); };
  }, []);
  const p = s.payment;
  const qr = useMemo(() => {
    if (!p?.payment_url || p.status !== "pending") return null;
    try { return paymentQr(p.payment_url); } catch { return null; }
  }, [p?.payment_url, p?.status]);
  const amountMinor = parseAmount(amount);
  const success = p?.status === "paid";
  const terminal = p && ["cancelled", "expired", "error"].includes(p.status);
  const waiting = s.active;
  const pendingAmount = p?.amount_minor ?? s.retryAmount ?? amountMinor;
  const open = async () => {
    if (!p?.payment_url || !qr) return;
    try { setLinkError(null); await openExternal(p.payment_url); }
    catch { setLinkError("Не удалось открыть браузер. Попробуйте ещё раз или отсканируйте QR."); }
  };
  return <div className="modal-backdrop payment-backdrop" onClick={onClose}>
    <div ref={ref} className="modal payment-dialog" role="dialog" aria-modal="true" aria-labelledby="payment-title" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
      <div className="modal-head">
        <h2 id="payment-title">Пополнение баланса</h2>
        <button className="icon-btn" aria-label="Закрыть пополнение" onClick={onClose}><X size={16} /></button>
      </div>
      <div className="modal-body">
        <div className="payment-balance"><span>Баланс AXIOM</span><strong>{s.wallet ? rubles(s.wallet.balance_minor) : "—"}</strong></div>
        {success ? <div className="payment-result payment-success" role="status">
          <span className="payment-result-icon"><Check size={24} /></span>
          <strong>Оплата получена</strong><div className="payment-amount">+{rubles(p.amount_minor)}</div>
          <span>Баланс: {s.wallet ? rubles(s.wallet.balance_minor) : "—"}</span>
        </div> : terminal ? <div className="payment-result" role="status">
          <Clock3 size={24} /><strong>{p.status === "expired" ? "Срок платежа истёк" : p.status === "cancelled" ? "Платёж отменён" : "Платёж не выполнен"}</strong>
          <span>Баланс не изменён. Можно создать новый платёж.</span>
        </div> : waiting || s.busy ? <div className="payment-result" role="status">
          <div className="payment-amount">{pendingAmount ? rubles(pendingAmount) : ""}</div>
          <span className="payment-status"><Loader2 className="spin" size={14} />{s.busy || p?.status === "creating" ? "Обрабатываем платёж…" : "Ожидание оплаты"}</span>
          {qr && <svg className="payment-qr" viewBox="0 0 65 65" role="img" aria-label="QR-код страницы оплаты" shapeRendering="crispEdges">
            <rect width="65" height="65" fill="white" />
            <path fill="black" d={qr.flatMap((row, y) => row.map((v, x) => v ? `M${x + 4},${y + 4}h1v1h-1z` : "")).join("")} />
          </svg>}
          {p?.status === "pending" && !qr && <span>Не удалось сформировать QR. Проверьте статус платежа.</span>}
          {qr && <button className="btn primary payment-open" onClick={() => void open()}><ExternalLink size={14} />Открыть страницу оплаты</button>}
          <span className="payment-note">{s.wallet?.automatic_confirmation ? "Баланс обновится после подтверждения банком." : "Автоматическая проверка не подключена. Это окно не подтверждает поступление денег."} Окно можно закрыть.</span>
        </div> : <>
          <div className="field-label">Пополнить баланс</div>
          <div className="payment-presets" role="group" aria-label="Сумма пополнения">
            {[100, 300, 500, 1000].map((v) => <button key={v} className={"btn" + (amountMinor === v * 100 ? " selected" : "")} disabled={!!s.retryAmount} aria-pressed={amountMinor === v * 100} onClick={() => setAmount(String(v))}>{rubles(v * 100)}</button>)}
          </div>
          <label className="field"><span className="field-label">Своя сумма, ₽</span>
            <input inputMode="decimal" value={amount} disabled={!!s.retryAmount} aria-describedby="payment-range" aria-invalid={amountMinor === null} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <span className="payment-note" id="payment-range">От 100 до 100 000 ₽ · Без сохранения данных карты</span>
          {s.wallet?.message && <p className="payment-note payment-unavailable">{s.wallet.message}</p>}
        </>}
        {(s.error || linkError) && <div className="payment-error" role="status">{s.error || linkError}</div>}
      </div>
      <div className="modal-foot">
        {waiting ? <>
          <button className="btn ghost" disabled={s.busy} onClick={() => void s.cancel()}>Отменить платёж</button>
          <button className="btn" disabled={s.busy} onClick={() => void s.check()}>Проверить</button>
        </> : success || terminal ? <>
          <button className="btn ghost" onClick={s.reset}>Новое пополнение</button>
          <button className="btn primary" onClick={onClose}>Готово</button>
        </> : <>
          <button className="btn ghost" onClick={onClose}>Отмена</button>
          {!s.wallet ? <button className="btn" onClick={() => void s.refresh()}>Повторить подключение</button> :
            <button className="btn primary" disabled={s.busy || !amountMinor || !s.wallet.available} onClick={() => amountMinor && void s.create(amountMinor)}>
              {s.busy ? "Создание…" : s.retryAmount ? "Повторить запрос" : "Продолжить"}
            </button>}
        </>}
      </div>
    </div>
  </div>;
}

export default function Balance() {
  const s = usePayments();
  const [open, setOpen] = useState(false);
  const value = s.wallet ? rubles(s.wallet.balance_minor) : "— ₽";
  return <>
    <button className={"balance-pill" + (s.payment?.status === "paid" ? " balance-paid" : "")} title={`Баланс ${value} · Пополнить`} aria-label={`Баланс ${value}. Пополнить баланс`} aria-haspopup="dialog" aria-expanded={open} onClick={() => { setOpen(true); if (!s.wallet) void s.refresh(); }}>
      <WalletIcon size={14} /><span className="balance-label">Баланс</span><strong>{value}</strong><span className="balance-plus"><Plus size={13} /></span>
      {s.active && <span className="balance-pending" aria-label="Ожидание оплаты" />}
    </button>
    {createPortal(<Presence open={open}><PaymentDialog store={s} onClose={() => setOpen(false)} /></Presence>, document.body)}
  </>;
}