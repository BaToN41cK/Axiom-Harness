import { useEffect, useRef, useState } from "react";
import { Check, Loader2, RotateCcw, X } from "lucide-react";
import type { Task } from "../types";
import { useLocale } from "../lib/locale";

/** Reject restores files, so every entry point requires explicit confirmation. */
export default function TaskReviewActions({ task, busy, onReview, onRecover }: {
  task: Task;
  busy: boolean;
  onReview: (id: string, decision: "accept" | "reject") => Promise<Task | null>;
  onRecover: (id: string) => Promise<Task | null>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const { t } = useLocale();
  const locked = useRef(false);
  const rejectButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (confirming) cancelButton.current?.focus(); }, [confirming]);
  function cancel() {
    if (locked.current) return;
    setConfirming(false);
    rejectButton.current?.focus();
  }
  async function decide(decision: "accept" | "reject") {
    if (busy || locked.current) return;
    locked.current = true;
    setPending(true);
    setError("");
    try {
      if (await onReview(task.id, decision)) setConfirming(false);
      else setError(t("ui.taskreview.not_saved"));
    } catch {
      setError(t("ui.taskreview.failed"));
    } finally { locked.current = false; setPending(false); }
  }
  async function recover() {
    if (busy || locked.current) return;
    locked.current = true;
    setPending(true);
    setError("");
    try {
      if (!await onRecover(task.id)) setError(t("ui.taskreview.recover_incomplete"));
    } catch {
      setError(t("ui.taskreview.recover_failed"));
    } finally { locked.current = false; setPending(false); }
  }
  if (task.review_recovery) return <div className="task-review-recovery" role="alert" aria-busy={pending}>
    <strong>{t("ui.taskreview.interrupted", { reason: task.review_recovery === "recovery_required" ? t("ui.taskreview.recovery_required") : t("ui.taskreview.unfinished_journal") })}</strong>
    <p>{task.review_recovery_detail || t("ui.taskreview.journal_default")}</p>
    {(task.review_recovery_paths ?? []).length > 0 && <div>{t("ui.taskreview.paths")} <ul>{task.review_recovery_paths?.map((path) => <li key={path}><code>{path}</code></li>)}</ul></div>}
    <p>{task.review_recovery_paths?.includes(".")
      ? t("ui.taskreview.parent_changed")
      : t("ui.taskreview.conflicts")}</p>
    <button type="button" className="task-btn mini ghost" disabled={busy || pending} onClick={() => void recover()}>{pending ? <Loader2 size={12} className="spin" /> : <RotateCcw size={12} />} {t("ui.taskreview.retry_recovery")}</button>
    {error && <p className="task-review-error" role="alert">{error}</p>}
  </div>;
  return <div className="task-review-actions" aria-busy={pending}>
    <button type="button" className="task-btn mini primary" disabled={busy || pending || confirming} onClick={() => void decide("accept")}><Check size={12} /> {t("ui.taskreview.accept")}</button>
    <button ref={rejectButton} type="button" className="task-btn mini danger" disabled={busy || pending} onClick={() => setConfirming(true)}><X size={12} /> {t("ui.taskreview.reject")}</button>
    {confirming && <div className="task-review-confirm" role="group" aria-label={t("ui.taskreview.confirm_aria")}
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); cancel(); } }}>
      <div>
        <strong>{t("ui.taskreview.reject_title")}</strong>
        <p>{t("ui.taskreview.reject_body")}</p>
        <p>{t("ui.taskreview.scope", { scope: task.scope ?? t("ui.taskreview.no_scope"), n: String(Object.keys(task.file_baselines ?? {}).length) })}</p>
      </div>
      <div className="task-review-confirm-actions">
        <button ref={cancelButton} type="button" className="task-btn mini ghost" disabled={pending} onClick={cancel}>{t("ui.common.cancel")}</button>
        <button type="button" className="task-btn mini danger" disabled={busy || pending} onClick={() => void decide("reject")}>{pending ? <Loader2 size={12} className="spin" /> : <X size={12} />} {t("ui.taskreview.restore_reject")}</button>
      </div>
    </div>}
    {error && <p className="task-review-error" role="alert">{error}</p>}
  </div>;
}
