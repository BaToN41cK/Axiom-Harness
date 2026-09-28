import { useEffect } from "react";

import type { PermissionDecision, PermissionRequest } from "../types";

interface Props {
  pending: PermissionRequest | null;
  onDecision: (decision: PermissionDecision) => void;
}

/**
 * W2.4+W4.9 — tool permission request: a blocked ASK tool call pauses here until
 * the user picks once / task / project / always / deny. The backend waits for
 * this real answer; Escape denies. HIGH/CRITICAL calls show their risk tier and
 * reason; scoped approvals never satisfy them (the backend asks per call).
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
  const tier = String(pending.risk ?? "SAFE").toUpperCase();
  const risk = tier === "CRITICAL" ? "критический" : tier === "HIGH" ? "высокий"
    : tier === "MEDIUM" ? "средний" : tier === "LOW" ? "низкий" : "минимальный";
  const commandText = typeof pending.command === "string" ? pending.command : "";
  const reasonText = typeof pending.reason === "string" ? pending.reason : "";
  const autonomyText = typeof pending.autonomy === "string" && pending.autonomy ? ` · режим ${pending.autonomy}` : "";
  const scoped = tier === "HIGH" || tier === "CRITICAL";
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
            Инструмент приостановлен до вашего ответа. Рабочая папка: <code>{pending.cwd}</code>, риск: {risk}{autonomyText}.
          </p>
          {commandText && <pre className="perm-args">{commandText}</pre>}
          {reasonText && <p className="about-text">{reasonText}</p>}
          {argumentsText !== "{}" && !commandText && <pre className="perm-args">{argumentsText}</pre>}
          {scoped && (
            <p className="about-text">
              Опасное действие: спрашиваем каждый раз, запоминание не применяется.
            </p>
          )}
          {!scoped && (
            <p className="about-text">
              «Один раз» выполнит только этот вызов. «Задача»/«Проект» запомнят в пределах задачи/проекта,
              «Всегда» — до конца сессии. Следующие вызовы в пределах scope не будут спрашивать.
            </p>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={() => onDecision("deny")}>Отклонить</button>
          <div className="modal-foot-spacer" />
          <button className="btn" onClick={() => onDecision("allow_once")}>Один раз</button>
          {!scoped && pending.task_id && <button className="btn" onClick={() => onDecision("allow_task")}>Задача</button>}
          {!scoped && <button className="btn" onClick={() => onDecision("allow_project")}>Проект</button>}
          {!scoped && <button className="btn primary" onClick={() => onDecision("allow_always")}>Всегда</button>}
        </div>
      </div>
    </div>
  );
}
