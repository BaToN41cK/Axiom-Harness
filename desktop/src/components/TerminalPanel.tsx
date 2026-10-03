import { useEffect, useRef, useState } from "react";
import { CircleCheck, CircleX, RotateCcw, Terminal, TriangleAlert } from "lucide-react";
import type { TerminalResult } from "../types";
import { useLocale } from "../lib/locale";

interface Props {
  cwd: string | null;
  enabled: boolean;
  history: { command: string; result: TerminalResult }[];
  pendingConfirm: string | null;
  onRun: (command: string) => void;
  onRerun: (command: string) => void;
  onConfirm: (allow: boolean) => void;
}

/** Real terminal in the workspace dir (§6–§7, §12). */
export default function TerminalPanel(props: Props) {
  const { cwd, enabled, history, pendingConfirm, onRun, onRerun, onConfirm } = props;
  const { t } = useLocale();
  const [draft, setDraft] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, pendingConfirm]);
  const submit = () => {
    const cmd = draft.trim();
    if (!cmd) return;
    setDraft("");
    onRun(cmd);
  };
  return (
    <section className="terminal">
      <div className="term-head">
        <Terminal size={13} strokeWidth={1.8} />
        <span className="term-cwd" title={cwd ?? ""}>{cwd ?? "—"}</span>
        {!enabled && <span className="term-off">{t("ui.terminal.off")}</span>}
      </div>
      <div className="term-body" ref={bodyRef}>
        {history.map((h, i) => {
          const failed = !h.result.ok;
          const exit = h.result.exit_code;
          return (
            <div key={i} className="term-entry">
              <div className="term-cmd">
                <span className="term-ps">›</span> {h.command}
                <button
                  className="icon-btn tiny term-rerun"
                  title={t("ui.terminal.rerun")}
                  disabled={!enabled}
                  onClick={() => onRerun(h.command)}
                >
                  <RotateCcw size={11} strokeWidth={1.8} />
                </button>
              </div>
              <pre className={"term-out" + (failed ? " err" : "")}>
                {h.result.ok ? h.result.content || t("ui.terminal.no_output") : h.result.error ?? t("ui.terminal.no_output")}
              </pre>
              {exit != null && (
                <div className={"term-exit " + (exit === 0 ? "ok" : "err")}>
                  {exit === 0 ? (
                    <CircleCheck size={11} strokeWidth={2} />
                  ) : (
                    <CircleX size={11} strokeWidth={2} />
                  )}
                  <span>{t("ui.terminal.exit_code", { n: String(exit) })}</span>
                </div>
              )}
            </div>
          );
        })}
        {pendingConfirm && (
          <div className="term-confirm">
            <TriangleAlert size={14} strokeWidth={1.9} />
            <div>
              <div className="term-confirm-title">{t("ui.terminal.confirm")}</div>
              <code className="term-confirm-cmd">{pendingConfirm}</code>
              <div className="term-confirm-row">
                <button className="mini-btn" onClick={() => onConfirm(false)}>{t("ui.common.cancel")}</button>
                <button className="mini-btn danger" onClick={() => onConfirm(true)}>{t("ui.terminal.run")}</button>
              </div>
            </div>
          </div>
        )}
        {history.length === 0 && !pendingConfirm && (
          <div className="term-empty">{t("ui.terminal.empty")}</div>
        )}
      </div>
      <div className="term-input-row">
        <span className="term-ps">›</span>
        <input
          className="term-input"
          value={draft}
          disabled={!enabled}
          placeholder={enabled ? t("ui.terminal.placeholder") : t("ui.terminal.placeholder_disabled")}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        />
      </div>
    </section>
  );
}
