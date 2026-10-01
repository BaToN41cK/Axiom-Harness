import { useEffect, useRef, useState, type CSSProperties } from "react";
import { AlertTriangle, Check, Loader2, RefreshCw, Settings2 } from "lucide-react";
import type { BootStep, Phase } from "../hooks/useAxiom";
import BlackHole from "./BlackHole";
import "../styles/boot-space.css";

interface Props {
  phase: Phase;
  steps: BootStep[];
  error: { message: string; hint: string | null; url: string } | null;
  onRetry: () => void;
  onRestartCore: () => void;
  onOpenSettings: () => void;
}

/* ------------------------------------------------------------------ smooth progress
   The real progress is discrete (N of 6 probes passed). The bar must not jump
   17% → 34%, so the displayed value is a separate number that:
     1. eases out towards the target every animation frame (frame-rate
        independent exponential lerp: k = 1 - e^(-dt/τ));
     2. keeps creeping inside the current step while the backend is still
        waiting (asymptotic 1 - e^(-t/τ), never reaches the next step), so the
        bar never freezes even when Ollama answers slowly;
     3. is monotonic — it never goes backwards (except a full reset on retry).
   The values are written straight into the DOM through refs: no React
   re-render at 60 fps. */
const LERP_TAU = 0.22; // s — how fast the bar catches up with the target
const LERP_TAU_DONE = 0.09; // s — final sprint to 100% before the main screen
const CREEP_TAU = 1.25; // s — how fast the in-step creep saturates
const CREEP_RUNNING = 0.9; // share of a step the bar may fill while it runs
const CREEP_IDLE = 0.4; // …and in the short gap between two probes

function useSmoothProgress(steps: BootStep[]) {
  const barRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const percentRef = useRef<HTMLSpanElement>(null);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  useEffect(() => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let raf = 0;
    let last = performance.now();
    let shown = 0;
    let shownPercent = -1;
    let doneMark = -1;
    let doneSince = last;

    const tick = (now: number) => {
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;

      const list = stepsRef.current;
      const total = Math.max(1, list.length);
      const done = list.filter((s) => s.state === "ok").length;
      const running = list.some((s) => s.state === "running");
      const failed = list.some((s) => s.state === "failed");
      const allDone = list.length > 0 && done >= list.length;
      const fresh = done === 0 && !running && !failed;

      if (done !== doneMark) {
        doneMark = done;
        doneSince = now;
      }

      let target: number;
      if (allDone) {
        target = 100;
      } else if (failed) {
        target = (done / total) * 100;
      } else {
        const t = (now - doneSince) / 1000;
        const cap = running ? CREEP_RUNNING : fresh ? 0.15 : CREEP_IDLE;
        target = ((done + cap * (1 - Math.exp(-t / CREEP_TAU))) / total) * 100;
      }

      const k = reduceMotion ? 1 : 1 - Math.exp(-dt / (allDone ? LERP_TAU_DONE : LERP_TAU));
      let next = shown + (target - shown) * k;
      // Monotonic: only a fresh restart (retry) may pull the bar back.
      if (next < shown && !(fresh && target === 0)) next = shown;
      if (fresh && target === 0 && shown > 0) next = 0;
      shown = next;

      if (barRef.current) barRef.current.style.transform = `scaleX(${(shown / 100).toFixed(4)})`;
      if (headRef.current) headRef.current.style.transform = `translateX(${(shown / 100) * (headRef.current.parentElement?.clientWidth ?? 0)}px)`;
      // 100% only when every probe really passed — never round up to it.
      const pct = allDone && shown > 99.4 ? 100 : Math.min(99, Math.floor(shown));
      if (pct !== shownPercent && percentRef.current) {
        shownPercent = pct;
        percentRef.current.textContent = String(pct);
      }

      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return { barRef, headRef, percentRef };
}

/* ---------------------------------------------------------------- status ticker
   A status change is a cross-fade, not a blink: the old line slides up and
   fades out while the new one rises from 6px below. Both live in the same grid
   cell, so the layout never jumps. */
function StatusTicker({ text }: { text: string }) {
  const seq = useRef(0);
  const [items, setItems] = useState([{ id: 0, text, leaving: false }]);

  useEffect(() => {
    setItems((prev) => {
      const current = prev[prev.length - 1];
      if (current && current.text === text && !current.leaving) return prev;
      seq.current += 1;
      return [...prev.map((item) => ({ ...item, leaving: true })), { id: seq.current, text, leaving: false }];
    });
    const timer = window.setTimeout(() => setItems((prev) => prev.filter((item) => !item.leaving)), 460);
    return () => window.clearTimeout(timer);
  }, [text]);

  return (
    <span className="boot-ticker" aria-live="polite">
      {items.map((item) => (
        <span
          key={item.id}
          className={"boot-ticker-item " + (item.leaving ? "is-leaving" : "is-entering")}
          aria-hidden={item.leaving || undefined}
        >
          {item.text}
        </span>
      ))}
    </span>
  );
}

function statusLine(steps: BootStep[]): string {
  const running = steps.find((s) => s.state === "running");
  if (running) return `${running.label}…`;
  if (steps.length > 0 && steps.every((s) => s.state === "ok")) return "Система готова";
  const next = steps.find((s) => s.state === "pending");
  if (next) return `${next.label}…`;
  return "Запуск AXIOM…";
}

/** The real boot sequence — every status is a probe that actually ran. */
export default function BootScreen({ phase, steps, error, onRetry, onRestartCore, onOpenSettings }: Props) {
  const failed = phase === "unavailable" || phase === "error";
  const { barRef, headRef, percentRef } = useSmoothProgress(steps);
  const doneCount = steps.filter((step) => step.state === "ok").length;

  return (
    <div className="boot boot--space">
      {/* Live procedural black hole (WebGL). Purely decorative. */}
      <BlackHole className="boot-blackhole-live" />
      <div className="boot-shade" aria-hidden />

      <div className="boot-inner">
        {/* Animated geometric logo */}
        <div className="boot-logo-container">
          <div className="boot-mark-wrapper">
            <div className="boot-mark" data-text="AXIOM">
              <span>A</span>
              <span>X</span>
              <span>I</span>
              <span>O</span>
              <span>M</span>
            </div>
            <div className="boot-mark boot-mark-glitch" data-text="AXIOM" aria-hidden>
              <span>A</span>
              <span>X</span>
              <span>I</span>
              <span>O</span>
              <span>M</span>
            </div>
          </div>

          <div className="boot-tagline">
            <span className="boot-tagline-bracket">[</span>
            LOCAL INTELLIGENCE
            <span className="boot-tagline-bracket">]</span>
          </div>
        </div>

        {!failed && (
          <>
            <div className="boot-steps">
              {steps.map((step, index) => (
                <div
                  key={step.id}
                  className={"boot-step " + step.state}
                  style={{ "--step-index": index } as CSSProperties}
                >
                  <span className="boot-step-icon">
                    {/* keyed by state → the new icon pops in instead of swapping */}
                    <span key={step.state} className="boot-step-icon-inner">
                      {step.state === "ok" && <Check size={13} strokeWidth={2.4} />}
                      {step.state === "running" && <Loader2 size={13} className="spin" />}
                      {step.state === "pending" && <span className="boot-dot" />}
                      {step.state === "failed" && <AlertTriangle size={13} strokeWidth={2.2} />}
                    </span>
                  </span>
                  <span className="boot-step-label">{step.label}</span>
                  {step.detail && (
                    <span key={step.detail} className="boot-step-detail">
                      {step.detail}
                    </span>
                  )}
                </div>
              ))}
            </div>

            <div className="boot-progress boot-pipeline">
              <div className="boot-pipeline-head">
                <div className="boot-pipeline-status">
                  <span className="boot-pipeline-kicker">Инициализация системы · {doneCount}/{steps.length}</span>
                  <span className="boot-pipeline-line">
                    <span className="boot-pipeline-caret" aria-hidden />
                    <StatusTicker text={statusLine(steps)} />
                  </span>
                </div>
                <div className="boot-pipeline-percent" aria-label="Прогресс загрузки">
                  <span ref={percentRef}>0</span>
                  <small>%</small>
                </div>
              </div>

              <div className="boot-pipeline-track">
                <div className="boot-pipeline-rail" />
                <div ref={barRef} className="boot-pipeline-fill" />
                <div ref={headRef} className="boot-pipeline-comet" aria-hidden />
                {steps.map((step, index) => (
                  <span
                    key={step.id}
                    className={"boot-pipeline-node " + step.state}
                    style={{ left: `${((index + 1) / steps.length) * 100}%` }}
                    title={step.label}
                  />
                ))}
                <span className="boot-pipeline-node origin ok" style={{ left: "0%" }} />
              </div>
            </div>
          </>
        )}

        {failed && error && (
          <div className="boot-error" role="alert">
            {/* Says it in words, not only in colour: the screen is red/black by
                design, so a tint alone can never carry "this is a problem". */}
            <div className="boot-error-badge">
              <AlertTriangle size={12} strokeWidth={2.6} aria-hidden />
              <span>Запуск остановлен</span>
            </div>
            <div className="boot-error-title">
              <AlertTriangle size={16} strokeWidth={2} aria-hidden />
              <span>{error.message}</span>
            </div>
            {error.hint && <div className="boot-error-hint">{error.hint}</div>}
            {phase === "unavailable" && (
              <>
                <p className="boot-error-causes-title">Вероятные причины</p>
                <ul className="boot-error-causes">
                  <li>Ollama не запущена — выполните <code>ollama serve</code></li>
                  <li>неверный адрес API в настройках</li>
                  <li>порт 11434 занят или соединение отклонено</li>
                </ul>
              </>
            )}
            <div className="boot-error-actions">
              <button className="btn primary" onClick={onRetry}>
                <RefreshCw size={14} strokeWidth={1.9} />
                <span>Повторить</span>
              </button>
              <button className="btn ghost" onClick={onRestartCore}>
                <RefreshCw size={14} strokeWidth={1.9} />
                <span>Перезапустить ядро</span>
              </button>
              <button className="btn ghost" onClick={onOpenSettings}>
                <Settings2 size={14} strokeWidth={1.9} />
                <span>Настройки</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
