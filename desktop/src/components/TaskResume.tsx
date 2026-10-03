import { useState } from "react";
import { Loader2, Play } from "lucide-react";
import type { Task } from "../types";
import { useLocale } from "../lib/locale";

/** Continue the same persisted task; interrupted writes require acknowledgement. */
export default function TaskResume({ task, busy, onResume }: {
  task: Task;
  busy: boolean;
  onResume: (id: string, acknowledge: boolean) => Promise<Task | null>;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [pending, setPending] = useState(false);
  const { t } = useLocale();
  const interrupted = Boolean(task.pending_tool) || task.plan?.steps.some((step) => step.state === "running");
  const completed = task.plan?.steps.filter((step) => step.state === "completed").length ?? 0;
  const resume = async () => {
    if (busy || pending || (interrupted && !acknowledged)) return;
    setPending(true);
    try { await onResume(task.id, acknowledged); } finally { setPending(false); setAcknowledged(false); }
  };
  return <div className="task-resume">
    <p>{t("ui.taskresume.text", { completed: String(completed) })}</p>
    {interrupted && <label className="task-acknowledge-check"><input type="checkbox" checked={acknowledged} disabled={busy || pending} onChange={(e) => setAcknowledged(e.target.checked)} /><span>{t("ui.taskresume.acknowledge")}</span></label>}
    <button type="button" className="task-btn primary" disabled={busy || pending || (interrupted && !acknowledged)} onClick={() => void resume()}>{pending ? <Loader2 size={13} className="spin" /> : <Play size={13} />}{pending ? t("ui.taskresume.resuming") : t("ui.taskresume.continue")}</button>
  </div>;
}