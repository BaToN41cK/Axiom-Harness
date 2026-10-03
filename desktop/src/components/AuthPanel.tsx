import { useEffect, useMemo, useState } from "react";
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  AlertTriangle, ArrowRight, Check, Copy, Eye, EyeOff, KeyRound, Loader2, Lock, RefreshCw,
  ShieldCheck, Sparkles, User, Wallet, X,
} from "lucide-react";
import type { usePayments, OAuthProvider, OAuthStage } from "../hooks/usePayments";
import { useLocale } from "../lib/locale";
import "../styles/auth.css";

type Payments = ReturnType<typeof usePayments>;

/* ---------------------------------------------------------------- brand marks */
export function GithubMark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="currentColor">
      <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.58.23 2.75.11 3.04.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
    </svg>
  );
}

export function GoogleMark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5Z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7Z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44Z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3a12 12 0 0 1-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5Z" />
    </svg>
  );
}

const PROVIDER_NAME: Record<OAuthProvider, string> = { github: "GitHub", google: "Google" };

/* ------------------------------------------------------------- password meter */
function passwordScore(pw: string): { score: 0 | 1 | 2 | 3 | 4; label: string } {
  if (!pw) return { score: 0, label: "" };
  let score = 0;
  if (pw.length >= 12) score += 1;
  if (pw.length >= 16) score += 1;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score += 1;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score += 1;
  if (pw.length < 12) score = Math.min(score, 1);
  const s = Math.max(1, Math.min(4, score)) as 1 | 2 | 3 | 4;
  return { score: s, label: ["", "ui.auth.pw.weak", "ui.auth.pw.medium", "ui.auth.pw.good", "ui.auth.pw.strong"][s] };
}

function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/* ------------------------------------------------------------- OAuth progress */
const STAGES: { id: OAuthStage; title: string; hint: string }[] = [
  { id: "starting", title: "ui.auth.stage.starting.title", hint: "ui.auth.stage.starting.hint" },
  { id: "browser", title: "ui.auth.stage.browser.title", hint: "ui.auth.stage.browser.hint" },
  { id: "waiting", title: "ui.auth.stage.waiting.title", hint: "ui.auth.stage.waiting.hint" },
  { id: "redeeming", title: "ui.auth.stage.redeeming.title", hint: "ui.auth.stage.redeeming.hint" },
];

function OAuthProgressView({ s }: { s: Payments }) {
  const { t } = useLocale();
  const o = s.oauth!;
  const [now, setNow] = useState(Date.now());
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(t);
  }, []);
  const order = STAGES.findIndex((stage) => stage.id === o.stage);
  const current = o.stage === "done" ? STAGES.length : order;
  const left = o.deadline - now;
  const elapsedShare = Math.min(1, (now - o.startedAt) / (o.deadline - o.startedAt));

  const copy = async () => {
    if (!o.url) return;
    try { await navigator.clipboard.writeText(o.url); setCopied(true); window.setTimeout(() => setCopied(false), 1600); } catch { /* clipboard unavailable */ }
  };

  return (
    <div className="auth-oauth" role="status" aria-live="polite">
      <div className={"auth-oauth-orb auth-oauth-orb--" + o.provider}>
        <span className="auth-oauth-ring" />
        <span className="auth-oauth-ring auth-oauth-ring--2" />
        <span className="auth-oauth-logo">{o.provider === "github" ? <GithubMark size={30} /> : <GoogleMark size={30} />}</span>
      </div>
      <h3 className="auth-oauth-title">{t("ui.auth.oauth_title", { provider: PROVIDER_NAME[o.provider] })}</h3>
      <p className="auth-oauth-sub">{t("ui.auth.oauth_sub")}</p>

      <ol className="auth-stepper">
        {STAGES.map((stage, index) => {
          const state = index < current ? "done" : index === current ? "active" : "todo";
          return (
            <li key={stage.id} className={"auth-step " + state}>
              <span className="auth-step-dot">
                {state === "done" ? <Check size={12} strokeWidth={3} /> : state === "active" ? <Loader2 size={12} className="spin" /> : index + 1}
              </span>
              <span className="auth-step-text">
                <strong>{t(stage.title)}</strong>
                <span>{t(stage.hint)}</span>
              </span>
            </li>
          );
        })}
      </ol>

      <div className="auth-oauth-timer">
        <div className="auth-oauth-timer-bar"><span style={{ transform: `scaleX(${1 - elapsedShare})` }} /></div>
        <span>{t("ui.auth.link_valid", { time: mmss(left) })}</span>
      </div>

      <div className="auth-oauth-actions">
        <button className="btn" disabled={!o.url} onClick={() => void s.reopenOAuth()}>
          <RefreshCw size={14} /> {t("ui.auth.reopen")}
        </button>
        <button className="btn" disabled={!o.url} onClick={() => void copy()}>
          {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? t("ui.code.copied") : t("ui.auth.copy_link")}
        </button>
        <button className="btn ghost" onClick={s.cancelOAuth}>
          <X size={14} /> {t("ui.auth.cancel")}
        </button>
      </div>

      <p className="auth-security">
        <ShieldCheck size={13} /> {t("ui.auth.security", { provider: PROVIDER_NAME[o.provider] })}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ AuthPanel */
export default function AuthPanel({ s }: { s: Payments }) {
  const { t } = useLocale();
  // Re-check OAuth availability every time the sign-in screen opens.
  useEffect(() => {
    if (s.providersState !== "ready") void s.loadProviders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const create = mode === "register";
  const strength = useMemo(() => passwordScore(password), [password]);
  const userValid = /^[a-zA-Z0-9._-]{3,48}$/.test(username.trim());
  const passValid = password.length >= 12;
  const matches = !create || (confirmation.length > 0 && confirmation === password);
  const canSubmit = userValid && passValid && matches && !s.busy;

  const onKey = (event: ReactKeyboardEvent<HTMLInputElement>) => setCaps(event.getModifierState?.("CapsLock") ?? false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    if (!userValid) { setLocalError(t("ui.auth.err.login")); return; }
    if (!passValid) { setLocalError(t("ui.auth.err.pass")); return; }
    if (create && password !== confirmation) { setLocalError(t("ui.auth.err.mismatch")); return; }
    void s.authenticate(username.trim(), password, create);
  };

  const switchMode = (next: "login" | "register") => {
    setMode(next); setLocalError(null); setConfirmation("");
  };

  const error = localError || s.error;

  return (
    <div className="auth">
      {/* -------------------------------------------------------- hero */}
      <aside className="auth-hero" aria-hidden>
        <div className="auth-hero-art">
          <span className="auth-hero-disk" />
          <span className="auth-hero-core" />
        </div>
        <div className="auth-hero-brand">AXIOM</div>
        <p className="auth-hero-tag">{t("ui.auth.hero_tag")}<br />{t("ui.auth.hero_tag2")}</p>
        <ul className="auth-hero-list">
          <li><Wallet size={14} /> {t("ui.auth.hero.balance")}</li>
          <li><ShieldCheck size={14} /> {t("ui.auth.hero.oauth")}</li>
          <li><KeyRound size={14} /> {t("ui.auth.hero.session")}</li>
          <li><Sparkles size={14} /> {t("ui.auth.hero.local")}</li>
        </ul>
      </aside>

      {/* -------------------------------------------------------- form */}
      <div className="auth-main">
        {s.oauth ? <OAuthProgressView s={s} /> : <>
          <div className="auth-head">
            <h3>{create ? t("ui.auth.create_title") : t("ui.auth.welcome_back")}</h3>
            <p>{create ? t("ui.auth.create_sub") : t("ui.auth.login_sub")}</p>
          </div>

          <div className="auth-tabs" role="tablist" aria-label={t("ui.auth.mode_aria")}>
            <button role="tab" aria-selected={!create} className={!create ? "active" : ""} onClick={() => switchMode("login")} disabled={s.busy}>{t("ui.auth.login")}</button>
            <button role="tab" aria-selected={create} className={create ? "active" : ""} onClick={() => switchMode("register")} disabled={s.busy}>{t("ui.auth.register")}</button>
            <span className="auth-tabs-thumb" style={{ transform: `translateX(${create ? 100 : 0}%)` }} />
          </div>

          <div className="auth-oauth-list">
            <button
              className="auth-provider auth-provider--github"
              disabled={s.busy || (s.providersState === "ready" && !s.providers.github)}
              onClick={() => void s.authenticateWithProvider("github")}
            >
              <span className="auth-provider-icon"><GithubMark /></span>
              <span className="auth-provider-text">{t("ui.auth.continue_github")}</span>
              {s.providersState === "loading" && !s.providers.github
                ? <span className="auth-provider-badge"><Loader2 size={11} className="spin" /> {t("ui.auth.checking")}</span>
                : s.providersState === "ready" && !s.providers.github
                  ? <span className="auth-provider-badge">{t("ui.auth.not_configured")}</span>
                  : <ArrowRight size={15} className="auth-provider-arrow" />}
            </button>
            <button
              className="auth-provider auth-provider--google"
              disabled={s.busy || (s.providersState === "ready" && !s.providers.google)}
              onClick={() => void s.authenticateWithProvider("google")}
            >
              <span className="auth-provider-icon"><GoogleMark /></span>
              <span className="auth-provider-text">{t("ui.auth.continue_google")}</span>
              {s.providersState === "loading" && !s.providers.google
                ? <span className="auth-provider-badge"><Loader2 size={11} className="spin" /> {t("ui.auth.checking")}</span>
                : s.providersState === "ready" && !s.providers.google
                  ? <span className="auth-provider-badge">{t("ui.auth.not_configured")}</span>
                  : <ArrowRight size={15} className="auth-provider-arrow" />}
            </button>
          </div>

          {s.providersState === "error" && (
            <div className="auth-hint auth-hint--warn auth-server-note">
              <AlertTriangle size={12} /> {t("ui.auth.server_note")}
              <button className="auth-link" onClick={() => void s.loadProviders()}>{t("ui.auth.check_again")}</button>
            </div>
          )}

          <div className="auth-divider"><span>{t("ui.auth.or_credentials")}</span></div>

          <form className="auth-form" onSubmit={submit} noValidate>
            <label className={"auth-field" + (username && !userValid ? " invalid" : "") + (userValid ? " valid" : "")}>
              <span className="auth-label">{t("ui.auth.username")}</span>
              <span className="auth-input">
                <User size={15} />
                <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="sergey.dev" maxLength={48} disabled={s.busy} autoFocus />
                {userValid && <Check size={14} className="auth-ok" />}
              </span>
              {create && <span className="auth-hint">{t("ui.auth.username_hint")}</span>}
            </label>

            <label className={"auth-field" + (password && !passValid ? " invalid" : "")}>
              <span className="auth-label">{t("ui.auth.password")}</span>
              <span className="auth-input">
                <Lock size={15} />
                <input type={show ? "text" : "password"} autoComplete={create ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} onKeyUp={onKey} onKeyDown={onKey} placeholder={t("ui.auth.password_placeholder")} maxLength={256} disabled={s.busy} />
                <button type="button" className="auth-eye" onClick={() => setShow(!show)} aria-label={show ? t("ui.auth.hide_password") : t("ui.auth.show_password")}>
                  {show ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </span>
              {caps && <span className="auth-hint auth-hint--warn"><AlertTriangle size={12} /> {t("ui.auth.caps")}</span>}
              {create && password && (
                <span className={"auth-meter s" + strength.score}>
                  <span className="auth-meter-bars"><i /><i /><i /><i /></span>
                  <span className="auth-meter-label">{t(strength.label)}</span>
                </span>
              )}
            </label>

            {create && (
              <label className={"auth-field" + (confirmation && !matches ? " invalid" : "") + (confirmation && matches ? " valid" : "")}>
                <span className="auth-label">{t("ui.auth.repeat_password")}</span>
                <span className="auth-input">
                  <Lock size={15} />
                  <input type={show ? "text" : "password"} autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} maxLength={256} disabled={s.busy} />
                  {confirmation && (matches ? <Check size={14} className="auth-ok" /> : <X size={14} className="auth-bad" />)}
                </span>
                {create && <span className="auth-hint">{t("ui.auth.save_password")}</span>}
              </label>
            )}

            {error && (
              <div className="auth-error" role="alert">
                <AlertTriangle size={14} />
                <span>{error}</span>
              </div>
            )}

            <button className="auth-submit" disabled={!canSubmit}>
              {s.busy ? <><Loader2 size={15} className="spin" /> {t("ui.auth.wait")}</> : <>{create ? t("ui.auth.submit_create") : t("ui.auth.submit_login")} <ArrowRight size={15} /></>}
            </button>
          </form>

          <p className="auth-foot">
            {create ? t("ui.auth.have_account") : t("ui.auth.new_here")}
            <button className="auth-link" onClick={() => switchMode(create ? "login" : "register")} disabled={s.busy}>
              {create ? t("ui.auth.signin_link") : t("ui.auth.create_link")}
            </button>
          </p>
        </>}
      </div>
    </div>
  );
}
