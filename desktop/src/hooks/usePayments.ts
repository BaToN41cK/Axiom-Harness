import { useCallback, useEffect, useRef, useState } from "react";
import { payments, paymentToken } from "../lib/payments";
import type { Account, Payment } from "../lib/payments";

const message = (error: unknown) => error instanceof Error ? error.message : "Не удалось связаться с платёжным сервером.";

export function usePayments() {
  const [account, setAccount] = useState<Account | null>(null);
  const [payment, setPayment] = useState<Payment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const mounted = useRef(false);

  const refresh = useCallback(async () => {
    const token = paymentToken.get();
    if (!token || lock.current) return;
    lock.current = true;
    try {
      const value = await payments.account(token);
      if (mounted.current) {
        setAccount(value);
        setPayment(value.latest_payment);
        setError(null);
      }
    } catch (e) {
      if (mounted.current) {
        setAccount(null);
        setPayment(null);
        setError(message(e));
      }
    } finally { lock.current = false; }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; };
  }, [refresh]);

  const authenticate = useCallback(async (username: string, password: string, create: boolean) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = create
        ? await payments.register(username, password)
        : await payments.login(username, password);
      paymentToken.set(result.access_token);
      if (mounted.current) {
        setAccount(result.account);
        setPayment(result.account.latest_payment);
      }
    } catch (e) {
      if (mounted.current) setError(message(e));
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  }, []);

  const createPayment = useCallback(async (operation: () => Promise<{ payment: Payment }>) => {
    if (lock.current || !paymentToken.get()) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await operation();
      if (mounted.current) setPayment(result.payment);
    } catch (e) {
      if (mounted.current) setError(message(e));
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  }, []);

  const buyProFromBalance = useCallback(async () => {
    const token = paymentToken.get();
    if (lock.current || !token) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await payments.buyProFromBalance(token);
      if (mounted.current) setAccount(result.account);
    } catch (e) {
      if (mounted.current) setError(message(e));
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  }, []);

  const active = payment?.status === "pending";
  useEffect(() => {
    if (!active || !payment || !paymentToken.get()) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const token = paymentToken.get();
      if (!token || lock.current) {
        if (!stopped) timer = setTimeout(poll, 3000);
        return;
      }
      lock.current = true;
      try {
        const result = await payments.status(token, payment.id);
        if (!stopped) {
          setPayment(result.payment);
          setAccount(result.account);
          setError(null);
        }
      } catch (e) { if (!stopped) setError(message(e)); }
      finally { lock.current = false; }
      if (!stopped && payment?.status === "pending") timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 1000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [payment?.id, active]);

  const signOut = useCallback(() => {
    const token = paymentToken.get();
    if (token) void payments.logout(token).catch(() => undefined);
    paymentToken.clear();
    setAccount(null);
    setPayment(null);
    setError(null);
  }, []);

  return {
    account, payment, error, busy, active, refresh, authenticate, signOut,
    createTopup: (amountRub: string) => createPayment(() => payments.topup(paymentToken.get() || "", amountRub)),
    buyPro: () => createPayment(() => payments.buyPro(paymentToken.get() || "")),
    buyProFromBalance,
  };
}
