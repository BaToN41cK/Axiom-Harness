import { useEffect } from "react";

import type { PermissionDecision, PermissionRequest } from "../types";
import { useLocale } from "../lib/locale";

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
  const { t } = useLocale();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDecision("deny");
    };
    if (pending) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, onDecision]);
  if (!pending) return null;
  const tier = String(pending.risk ?? "SAFE").toUpperCase();
  const riskKey = tier === "CRITICAL" ? "ui.confirm.risk.critical" : tier === "HIGH" ? "ui.confirm.risk.high"
    : tier === "MEDIUM" ? "ui.confirm.risk.medium" : tier === "LOW" ? "ui.confirm.risk.low" : "ui.confirm.risk.safe";
  const risk = t(riskKey);
  const commandText = typeof pending.command === "string" ? pending.command : "";
  const reasonText = typeof pending.reason === "string" ? pending.reason : "";
  const autonomyText = typeof pending.autonomy === "string" && pending.autonomy ? ` · ${t("ui.confirm.mode", { mode: pending.autonomy })}` : "";
  const scoped = tier === "HIGH" || tier === "CRITICAL";
  const argumentsText = JSON.stringify(pending.arguments ?? {}, null, 2);
  return (
    <div className="modal-backdrop" onClick={() => onDecision("deny")}>
      <div className="modal confirm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{t("ui.confirm.title")}</h2>
        </div>
        <div className="modal-body">
          <code className="confirm-detail">{pending.tool}</code>
          <p className="about-text">
            {t("ui.confirm.paused", { cwd: pending.cwd, risk, autonomy: autonomyText })}
          </p>
          {commandText && <pre className="perm-args">{commandText}</pre>}
          {reasonText && <p className="about-text">{reasonText}</p>}
          {argumentsText !== "{}" && !commandText && <pre className="perm-args">{argumentsText}</pre>}
          {scoped && (
            <p className="about-text">
              {t("ui.confirm.danger_note")}
            </p>
          )}
          {!scoped && (
            <p className="about-text">
              {t("ui.confirm.scope_note")}
            </p>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={() => onDecision("deny")}>{t("ui.confirm.deny")}</button>
          <div className="modal-foot-spacer" />
          <button className="btn" onClick={() => onDecision("allow_once")}>{t("ui.confirm.allow_once")}</button>
          {!scoped && pending.task_id && <button className="btn" onClick={() => onDecision("allow_task")}>{t("ui.confirm.allow_task")}</button>}
          {!scoped && <button className="btn" onClick={() => onDecision("allow_project")}>{t("ui.confirm.allow_project")}</button>}
          {!scoped && <button className="btn primary" onClick={() => onDecision("allow_always")}>{t("ui.confirm.allow_always")}</button>}
        </div>
      </div>
    </div>
  );
}
