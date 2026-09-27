import { useEffect } from "react";

import type { PermissionDecision, PermissionRequest } from "../types";

interface Props {
  pending: PermissionRequest | null;
  onDecision: (decision: PermissionDecision) => void;
}

/**
 * W2.4 — tool permission request: a blocked ASK tool call pauses here until
 * the user picks "Allow once" / "Always for this tool" / "Deny". The backend
 * waits for this real answer; Escape denies.
 */
export default function ConfirmDialog(props: Props) {
  const { pending, onDecision } = props;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDecision("deny");
    };
    if (pending) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, onDecision]);
  if (!pending) return null;
  const risk = pending.risk === "dangerous" ? "высокий" : pending.risk === "medium" ? "средний" : "низкий";
  const argumentsText = JSON.stringify(pending.arguments ?? {}, null, 2);
  return (
    <div className="modal-backdrop" onClick={() => onDecision("deny")}>
      <div className="modal confirm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Запрос разрешения</h2>
        </div>
        <div className="modal-body">
          <code className="confirm-detail">{pending.tool}</code>
          <p className="about-text">
            Инструмент приостановлен до вашего ответа. Рабочая папка: <code>{pending.cwd}</code>, риск: {risk}.
          </p>
          {argumentsText !== "{}" && <pre className="perm-args">{argumentsText}</pre>}
          <p className="about-text">
            «Один раз» выполнит только этот вызов. «Всегда» запомнит инструмент до конца сессии —
            следующие вызовы не будут спрашивать.
          </p>
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={() => onDecision("deny")}>Отклонить</button>
          <div className="modal-foot-spacer" />
          <button className="btn" onClick={() => onDecision("allow_once")}>Один раз</button>
          <button className="btn primary" onClick={() => onDecision("allow_always")}>Всегда для этого инструмента</button>
        </div>
      </div>
    </div>
  );
}
