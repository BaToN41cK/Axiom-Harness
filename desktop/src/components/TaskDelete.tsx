import { useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import type { Task } from "../types";

/** Delete the persisted task record after explicit confirmation. */
export default function TaskDelete({ task, busy, onDelete }: {
  task: Task;
  busy: boolean;
  onDelete: (id: string) => Promise<boolean>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const remove = async () => {
    if (busy || pending) return;
    setPending(true);
    try { if (await onDelete(task.id)) setConfirming(false); } finally { setPending(false); }
  };
  if (confirming) return <div className="task-delete-confirm" role="alert">
    <b>Удалить задачу?</b>
    <p>План, результаты шагов, команды и проверки будут удалены из задачника. Изменённые файлы проекта не изменятся.</p>
    <div>
      <button type="button" className="task-btn ghost" disabled={busy || pending} onClick={() => setConfirming(false)}>Отмена</button>
      <button type="button" className="task-btn danger" disabled={busy || pending} onClick={() => void remove()}>{pending ? <Loader2 size={13} className="spin" /> : <Trash2 size={13} />} Удалить</button>
    </div>
  </div>;
  return <button type="button" className="task-btn danger" disabled={busy} aria-label="Удалить задачу" onClick={() => setConfirming(true)}>
    <Trash2 size={13} /> Удалить задачу
  </button>;
}