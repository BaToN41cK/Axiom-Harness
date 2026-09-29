import { useCallback, useEffect, useRef, useState } from "react";
import { payments } from "../lib/payments";
import type { Payment, PaymentReply, Wallet } from "../lib/payments";

const message = (error: unknown) => error instanceof Error ? error.message : "Не удалось связаться с платёжным сервером";

export function usePayments() {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [payment, setPayment] = useState<Payment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const attempt = useRef<{ amount: number; key: string } | null>(null);
  const mounted = useRef(false);
  const apply = useCallback((reply: PaymentReply) => {
    if (!mounted.current) return;
    setPayment(reply.payment);
    setWallet((w) => w ? { ...w, balance_minor: reply.balance_minor, payment: reply.payment } : w);
    setError(null);
  }, []);
  const refresh = useCallback(async () => {
    if (lock.current) return;
    lock.current = true;
    try {
      const value = await payments.wallet();
      if (mounted.current) { setWallet(value); setPayment(value.payment); setError(null); }
    } catch (e) { if (mounted.current) setError(message(e)); }
    finally { lock.current = false; }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; };
  }, [refresh]);
  const perform = useCallback(async (operation: () => Promise<PaymentReply>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try { apply(await operation()); }
    catch (e) { if (mounted.current) setError(message(e)); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }, [apply]);
  const active = payment?.status === "pending" || payment?.status === "creating";
  useEffect(() => {
    if (!active || !payment) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!lock.current) {
        lock.current = true;
        try { const reply = await payments.status(payment.id); if (!stopped) apply(reply); }
        catch (e) { if (!stopped) setError(message(e)); }
        finally { lock.current = false; }
      }
      if (!stopped) timer = setTimeout(poll, 4000);
    };
    timer = setTimeout(poll, 1000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [payment?.id, active, apply]);
  return {
    wallet, payment, error, busy, active, refresh,
    create: (amount: number) => {
      if (active) return;
      if (!attempt.current) attempt.current = { amount, key: crypto.randomUUID() };
      // Retrying an ambiguous network failure must not create a second order.
      const current = attempt.current;
      return perform(() => payments.create(current.amount, current.key));
    },
    cancel: () => payment && perform(() => payments.cancel(payment.id)),
    check: () => payment && perform(() => payments.status(payment.id)),
    reset: () => { if (!active && !busy) { attempt.current = null; setPayment(null); setError(null); } },
    retryAmount: attempt.current?.amount ?? null,
  };
}