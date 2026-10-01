import { useEffect, useRef, useState } from "react";
import { CircleCheck, CircleX, RotateCcw, Terminal, TriangleAlert } from "lucide-react";
import type { TerminalResult } from "../types";

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
        {!enabled && <span className="term-off">выключен</span>}
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
                  title="Повторить команду"
                  disabled={!enabled}
                  onClick={() => onRerun(h.command)}
                >
                  <RotateCcw size={11} strokeWidth={1.8} />
                </button>
              </div>
              <pre className={"term-out" + (failed ? " err" : "")}>
                {h.result.ok ? h.result.content || "(no output)" : h.result.error ?? "(no output)"}
              </pre>
              {exit != null && (
                <div className={"term-exit " + (exit === 0 ? "ok" : "err")}>
                  {exit === 0 ? (
                    <CircleCheck size={11} strokeWidth={2} />
                  ) : (
                    <CircleX size={11} strokeWidth={2} />
                  )}
                  <span>код {exit}</span>
                </div>
              )}
            </div>
          );
        })}
        {pendingConfirm && (
          <div className="term-confirm">
            <TriangleAlert size={14} strokeWidth={1.9} />
            <div>
              <div className="term-confirm-title">Выполнить команду?</div>
              <code className="term-confirm-cmd">{pendingConfirm}</code>
              <div className="term-confirm-row">
                <button className="mini-btn" onClick={() => onConfirm(false)}>Отмена</button>
                <button className="mini-btn danger" onClick={() => onConfirm(true)}>Выполнить</button>
              </div>
            </div>
          </div>
        )}
        {history.length === 0 && !pendingConfirm && (
          <div className="term-empty">pytest · npm run dev · git status — команды выполняются в папке проекта</div>
        )}
      </div>
      <div className="term-input-row">
        <span className="term-ps">›</span>
        <input
          className="term-input"
          value={draft}
          disabled={!enabled}
          placeholder={enabled ? "команда…" : "терминал отключён в настройках"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        />
      </div>
    </section>
  );
}
