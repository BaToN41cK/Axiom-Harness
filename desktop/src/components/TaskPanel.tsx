import { useState } from "react";
import { ListChecks, Play, RefreshCw, Square } from "lucide-react";
import type { Task, TaskState } from "../types";
import "./TaskPanel.css";

const LABELS: Record<TaskState, string> = {
  pending: "Ожидает запуска", analyzing: "Анализ", planning: "Планирование",
  executing: "Выполнение", verifying: "Проверка", waiting_for_user: "Нужно ваше решение",
  completed: "Завершена", failed: "Ошибка", cancelled: "Остановлена",
};

interface Props {
  tasks: Task[];
  busy: boolean;
  activeId: string | null;
  onStart: (goal: string) => Promise<Task | null>;
  onResume: (id: string, acknowledge: boolean) => Promise<Task | null>;
  onCancel: (id: string) => Promise<boolean>;
  onRefresh: () => Promise<void>;
}

function TaskCard({ task, busy, activeId, onResume, onCancel }: Omit<Props, "tasks" | "onStart" | "onRefresh"> & { task: Task }) {
  const [acknowledged, setAcknowledged] = useState(false);
  const interrupted = Boolean(task.pending_tool) || task.plan?.steps.some((step) => step.state === "running");
  return (
    <article className="task-card">
      <strong>{task.goal}</strong>
      <p role="status">{LABELS[task.state]}</p>
      <small>{task.id}</small>
      {task.detail && <p>{task.detail}</p>}
      {task.plan && (
        <ol>{task.plan.steps.map((step) => (
          <li key={step.id}>
            <span>{step.goal} — {step.state}</span>
            {step.result && <details><summary>Результат шага</summary><pre>{step.result}</pre></details>}
          </li>
        ))}</ol>
      )}
      {task.changed_files.length > 0 && <p>Изменения через file tools: {task.changed_files.join(", ")}</p>}
      {task.tests.length > 0 && <details>
        <summary>Отчёты проверок ({task.tests.length})</summary>
        <pre>{JSON.stringify(task.tests, null, 2)}</pre>
      </details>}
      {task.errors.length > 0 && <details>
        <summary>Ошибки ({task.errors.length})</summary>
        <pre>{task.errors.map((error) => error.message).join("\n")}</pre>
      </details>}
      {activeId === task.id ? (
        <button onClick={() => void onCancel(task.id)}><Square size={13} /> Остановить</button>
      ) : task.state !== "completed" && (
        <>
          {interrupted && <label>
            <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
            Проверил файлы и команды после прерывания; разрешаю продолжить незавершённый шаг
          </label>}
          <button disabled={busy || (interrupted && !acknowledged)} onClick={() => {
            void onResume(task.id, acknowledged);
            setAcknowledged(false);
          }}><Play size={13} /> Продолжить</button>
        </>
      )}
    </article>
  );
}

export default function TaskPanel(props: Props) {
  const [goal, setGoal] = useState("");
  return (
    <section className="task-panel" aria-label="Задачи">
      <header><ListChecks size={15} /> Задачи
        <button title="Обновить задачи" aria-label="Обновить задачи" onClick={() => void props.onRefresh()}>
          <RefreshCw size={14} />
        </button>
      </header>
      <form onSubmit={(event) => {
        event.preventDefault();
        if (goal.trim()) void props.onStart(goal.trim()).then((task) => { if (task) setGoal(""); });
      }}>
        <textarea aria-label="Цель задачи" value={goal} maxLength={16000} disabled={props.busy}
          placeholder="Опишите coding-задачу…" onChange={(event) => setGoal(event.target.value)} />
        <button disabled={props.busy || !goal.trim()}><Play size={13} /> Запустить</button>
      </form>
      <p>Состояние сохраняется отдельно от чата. Без выполненных проверок задача не получает статус «Завершена».</p>
      {props.tasks.length === 0 && <p>Сохранённых задач в этом workspace нет.</p>}
      {props.tasks.map((task) => <TaskCard key={task.id} {...props} task={task} />)}
    </section>
  );
}
