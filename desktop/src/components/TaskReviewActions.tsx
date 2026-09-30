import { useEffect, useRef, useState } from "react";
import { Check, Loader2, RotateCcw, X } from "lucide-react";
import type { Task } from "../types";

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
      else setError("Решение не сохранено. Проверьте сообщение об ошибке и состояние файлов.");
    } catch {
      setError("Не удалось выполнить ревью. Проверьте состояние файлов перед повтором.");
    } finally { locked.current = false; setPending(false); }
  }
  async function recover() {
    if (busy || locked.current) return;
    locked.current = true;
    setPending(true);
    setError("");
    try {
      if (!await onRecover(task.id)) setError("Восстановление не завершено. Проверьте конфликтующие файлы и обновите задачи.");
    } catch {
      setError("Не удалось завершить восстановление. Файлы не следует удалять без проверки.");
    } finally { locked.current = false; setPending(false); }
  }
  if (task.review_recovery) return <div className="task-review-recovery" role="alert" aria-busy={pending}>
    <strong>Ревью прервано · {task.review_recovery === "recovery_required" ? "нужно ручное восстановление" : "есть незавершённый журнал"}</strong>
    <p>{task.review_recovery_detail || "Обнаружен незавершённый журнал ревью. Не принимайте решение, пока состояние файлов не проверено."}</p>
    {(task.review_recovery_paths ?? []).length > 0 && <div>Пути, требующие проверки: <ul>{task.review_recovery_paths?.map((path) => <li key={path}><code>{path}</code></li>)}</ul></div>}
    <p>{task.review_recovery_paths?.includes(".")
      ? "Изменился родительский каталог или корень проекта. Верните исходный каталог после проверки его содержимого; не удаляйте сохранённые копии до завершения восстановления."
      : "Сохраните конфликтующие файлы вне их текущих путей после ручной проверки. Повторная попытка не перезаписывает чужие изменения; сохранённые копии не удаляйте до успешного завершения."}</p>
    <button type="button" className="task-btn mini ghost" disabled={busy || pending} onClick={() => void recover()}>{pending ? <Loader2 size={12} className="spin" /> : <RotateCcw size={12} />} Повторить безопасное восстановление</button>
    {error && <p className="task-review-error" role="alert">{error}</p>}
  </div>;
  return <div className="task-review-actions" aria-busy={pending}>
    <button type="button" className="task-btn mini primary" disabled={busy || pending || confirming} onClick={() => void decide("accept")}><Check size={12} /> Принять</button>
    <button ref={rejectButton} type="button" className="task-btn mini danger" disabled={busy || pending} onClick={() => setConfirming(true)}><X size={12} /> Отклонить</button>
    {confirming && <div className="task-review-confirm" role="group" aria-label="Подтверждение восстановления файлов"
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); cancel(); } }}>
      <div>
        <strong>Отклонить изменения?</strong>
        <p>AXIOM восстановит сохранённые файлы до задачи и удалит созданные ею файлы. Если обнаружены последующие ручные правки, восстановление будет заблокировано.</p>
        <p>Проект: {task.scope ?? "не указан"} · сохранённых путей: {Object.keys(task.file_baselines ?? {}).length}</p>
      </div>
      <div className="task-review-confirm-actions">
        <button ref={cancelButton} type="button" className="task-btn mini ghost" disabled={pending} onClick={cancel}>Отмена</button>
        <button type="button" className="task-btn mini danger" disabled={busy || pending} onClick={() => void decide("reject")}>{pending ? <Loader2 size={12} className="spin" /> : <X size={12} />} Восстановить и отклонить</button>
      </div>
    </div>}
    {error && <p className="task-review-error" role="alert">{error}</p>}
  </div>;
}
