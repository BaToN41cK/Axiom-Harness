import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Crown, Plus, Wallet, X } from "lucide-react";
import AuthPanel from "./AuthPanel";
import AccountView from "./AccountView";
import { openExternal } from "../bridge";
import Presence from "./Presence";
import { usePayments } from "../hooks/usePayments";
import { axiomUsd, paymentBackendConfigured, paymentToken } from "../lib/payments";
import { paymentQr } from "../lib/paymentQr";
import "../styles/payments.css";

export default function Balance() {
  const s = usePayments();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("300");
  const [linkError, setLinkError] = useState<string | null>(null);
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

  const openPayment = async () => {
    const url = s.payment?.payment_url;
    if (!url || !url.startsWith("https://")) return;
    try { setLinkError(null); await openExternal(url); }
    catch { setLinkError("Не удалось открыть браузер. Отсканируйте QR-код или попробуйте ещё раз."); }
  };
  const balanceLabel = s.account ? axiomUsd(s.account.balance_minor) : "—";
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
      <Wallet size={14} /><span className="balance-label">{s.account ? "Баланс" : "Войти"}</span><strong>{s.account ? balanceLabel : "AXIOM"}</strong>
      {s.account?.pro_active && <Crown size={13} className="balance-crown" aria-label="AXIOM PRO" />}
      <span className="balance-plus"><Plus size={13} /></span>
      {pending && <span className="balance-pending" aria-label="Ожидание оплаты" />}
    </button>
    {createPortal(<Presence open={open}>
      <div className="modal-backdrop payment-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
        <section className={"modal payment-dialog" + (paymentBackendConfigured && !s.account ? " payment-dialog--auth" : s.account ? " payment-dialog--account" : "")} role="dialog" aria-modal="true" aria-labelledby="payment-title">
          <div className="modal-head">
            <h2 id="payment-title">{s.account ? "Аккаунт" : "Вход в AXIOM"}</h2>
            <button className="icon-btn" aria-label="Закрыть платежи" onClick={() => setOpen(false)}><X size={16} /></button>
          </div>
          {!paymentBackendConfigured ? <div className="modal-body">
            <p className="payment-note payment-unavailable">Платёжный сервер не настроен в этой сборке AXIOM.</p>
          </div> : !s.account ? <div className="modal-body auth-body">
            <AuthPanel s={s} />
          </div> : <div className="modal-body acct-body">
            <AccountView s={s} amount={amount} setAmount={setAmount} qr={qr} onOpenPayment={() => void openPayment()} linkError={linkError} />
          </div>}
        </section>
      </div>
    </Presence>, document.body)}
  </>;
}
