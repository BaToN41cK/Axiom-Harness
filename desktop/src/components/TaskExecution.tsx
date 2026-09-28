import { ArrowLeft, Check, Circle, FileCode2, Loader2, TriangleAlert, X } from "lucide-react";
import { TaskCard } from "./TaskCard";
import TaskDelete from "./TaskDelete";
import TaskResume from "./TaskResume";
import type { Task } from "../types";
import type { AxiomStore } from "../hooks/useAxiom";

interface Props {
  task: Task | null;
  store: AxiomStore;
  onBack: () => void;
}

const LABELS: Record<Task["state"], string> = {
  pending: "Готова к запуску", analyzing: "Анализ проекта", planning: "Составление плана",
  executing: "Выполнение", verifying: "Проверка результата", waiting_for_permission: "Ожидает разрешения",
  waiting_for_user: "Требуется решение", completed: "Завершена", failed: "Ошибка", cancelled: "Остановлена",
};

/** Human names for the W4.3 context categories shown in the budget rows. */
const BUDGET_LABELS: Record<string, string> = {
  system: "Система", project: "Проект", task: "Задача", files: "Файлы",
  tool_results: "Результаты инструментов", conversation: "Диалог",
};

/** Real added/removed line counts of a unified diff (headers excluded). */
function diffCounts(diff: string): { add: number; del: number } {
  let add = 0;
  let del = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) add += 1;
    else if (line.startsWith("-")) del += 1;
  }
  return { add, del };
}

/** One collapsible changed-file diff with +/- counts, driven by task state. */
function DiffFile({ path, diff }: { path: string; diff: string }) {
  const placeholder = diff.startsWith("(File created");
  const { add, del } = diffCounts(diff);
  const lines = diff.split("\n");
  const shown = lines.slice(0, 1500);
  return (
    <details className="task-diff-file">
      <summary>
        <code className="task-diff-path">{path}</code>
        {!placeholder && <span className="task-diff-counts"><b className="add">+{add}</b><b className="del">−{del}</b></span>}
      </summary>
      {placeholder ? <p className="task-diff-note">{diff}</p> : (
        <pre className="task-diff-body">{shown.map((line, index) => (
          <span
            key={index}
            className={line.startsWith("+++") || line.startsWith("---") ? "meta" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : ""}
          >{line || " "}</span>
        ))}</pre>
      )}
      {!placeholder && lines.length > shown.length && <p className="task-diff-note">… diff усечён для отображения</p>}
    </details>
  );
}

export default function TaskExecution({ task, store, onBack }: Props) {
  const steps = task?.plan?.steps ?? [];
  const completed = steps.filter((step) => step.state === "completed").length;
  const progress = steps.length ? Math.round(completed / steps.length * 100) : 0;
  const activeStep = steps.find((step) => step.state === "running");
  const running = ["analyzing", "planning", "executing", "verifying", "waiting_for_permission"].includes(task?.state ?? "");
  const resumable = ["cancelled", "failed", "waiting_for_user"].includes(task?.state ?? "");
  const diffEntries = Object.entries(task?.diffs ?? {});
  const report = task?.context_report ?? null;
  const budgetRows = Object.entries(report?.categories ?? {}).filter(([cat, used]) => used > 0 || (report?.budgets?.[cat] ?? 0) > 0);
  return (
    <section className="task-execution" aria-label="Выполнение задачи">
      <header className="task-execution-head">
        <button className="task-execution-back" onClick={onBack} title="Вернуться в чат"><ArrowLeft size={15} /> Чат</button>
        <span className="task-execution-kicker">TASK EXECUTION</span>
        {task && <span className={`task-execution-state ${task.state}`}><span />{LABELS[task.state]}</span>}
      </header>
      {!task ? (
        <div className="task-execution-loading"><Loader2 size={18} className="spin" /> Запускаю задачу…</div>
      ) : (
        <div className="task-execution-scroll">
          <div className="task-execution-title-row">
            <div><h1>{task.goal}</h1><p>{task.detail || LABELS[task.state]}</p></div>
            {steps.length > 0 && <strong>{progress}%</strong>}
          </div>
          {steps.length > 0 && <div className="task-execution-progress"><span style={{ width: `${progress}%` }} /></div>}
          {resumable && <TaskResume key={`${task.id}:${task.revision}`} task={task} busy={store.generating || store.taskRequestPending} onResume={store.resumeTask} />}
          {activeStep && running && <div className="task-execution-now"><Loader2 size={15} className="spin" /><div><b>Сейчас выполняется</b><span>{activeStep.goal}</span></div></div>}
          {task.pending_tool && <div className="task-execution-warning"><TriangleAlert size={15} /><span><b>{task.state === "waiting_for_permission" ? "Ожидается разрешение" : running ? "Активный инструмент" : "Прерванный инструмент"}</b><code>{String(task.pending_tool.name ?? "инструмент")}</code><pre>{JSON.stringify(task.pending_tool.arguments ?? {}, null, 2)}</pre></span></div>}
          <div className="task-execution-section"><div className="task-execution-section-label">План выполнения</div>
            {steps.length ? <ol className="task-execution-steps">{steps.map((step) => (
              <li key={step.id} className={step.state}>
                <span className="task-execution-step-icon">{step.state === "completed" ? <Check size={13} /> : step.state === "running" && running ? <Loader2 size={13} className="spin" /> : step.state === "failed" ? <X size={13} /> : <Circle size={9} />}</span>
                <span>{step.goal}</span>{step.result && <small>{step.result}</small>}
              </li>
            ))}</ol> : <p className="task-execution-empty">План появится после анализа задачи.</p>}
          </div>
          {task.changed_files.length > 0 && <div className="task-execution-section"><div className="task-execution-section-label"><FileCode2 size={13} /> Изменённые файлы</div><div className="task-execution-files">{task.changed_files.map((file) => <code key={file}>{file}</code>)}</div></div>}
          {diffEntries.length > 0 && (
            <div className="task-execution-section">
              <div className="task-execution-section-label"><FileCode2 size={13} /> Diff изменений ({diffEntries.length})</div>
              <div className="task-execution-review">
                {task.state === "completed" ? (task.review_status === "pending" ? (
                  <>
                    <button type="button" className="task-btn mini primary" disabled={store.taskRequestPending} onClick={() => void store.reviewTask(task.id, "accept")}><Check size={12} /><span>Принять</span></button>
                    <button type="button" className="task-btn mini danger" disabled={store.taskRequestPending} onClick={() => void store.reviewTask(task.id, "reject")}><X size={12} /><span>Отклонить</span></button>
                  </>
                ) : (
                  <span className={`task-execution-review-state ${task.review_status}`}>{task.review_status === "accepted" ? "Изменения приняты" : "Изменения отклонены"}</span>
                )) : <span className="task-execution-review-state pending">Ревью станет доступно после завершения</span>}
              </div>
              {diffEntries.map(([file, diff]) => <DiffFile key={file} path={file} diff={diff} />)}
            </div>
          )}
          {budgetRows.length > 0 && (
            <div className="task-execution-section">
              <div className="task-execution-section-label">Бюджет контекста</div>
              <div className="task-execution-budgets">
                {budgetRows.map(([cat, used]) => {
                  const budget = report?.budgets?.[cat] ?? 0;
                  const pct = budget > 0 ? Math.min(100, Math.round(used / budget * 100)) : used > 0 ? 100 : 0;
                  const over = (report?.over_budget ?? []).includes(cat);
                  return (
                    <div className={`task-execution-budget${over ? " over" : ""}`} key={cat} title={`${cat}: ${used} / ${budget}`}>
                      <span className="task-execution-budget-cat">{BUDGET_LABELS[cat] ?? cat}</span>
                      <span className="task-execution-budget-bar"><span style={{ width: `${pct}%` }} /></span>
                      <span className="task-execution-budget-num">{used} / {budget}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {task.commands.length > 0 && <div className="task-execution-section"><div className="task-execution-section-label">Реальные команды</div>{task.commands.map((command, index) => <details key={index}><summary>{String(command.tool ?? "command")} · {String(command.state ?? "")} {String(command.command ?? "")}</summary><pre>{String(command.output ?? "Вывод пока не получен")}</pre></details>)}</div>}
          {task.tests.length > 0 && <div className="task-execution-section"><div className="task-execution-section-label">Проверки</div>{task.tests.map((test, index) => <pre key={index} className={test.ok === true && test.executed === true ? "ok" : "error"}>{String(test.summary ?? test.error ?? JSON.stringify(test))}</pre>)}</div>}
          {task.errors.length > 0 && <div className="task-execution-error"><b>Ошибка выполнения</b><span>{task.errors[task.errors.length - 1].message}</span></div>}
          {task.state === "completed" && <div className="task-execution-done"><Check size={15} />{task.review_status === "accepted" ? "Изменения приняты" : task.review_status === "rejected" ? "Изменения отклонены" : "Результат готов к ревью"}</div>}
          <div className="task-execution-actions">
            {store.activeTaskId === task.id && <button className="task-execution-stop" onClick={() => void store.cancelTask(task.id)}><X size={14} /> Остановить выполнение</button>}
            {!running && <TaskDelete key={`${task.id}:${task.revision}`} task={task} busy={store.generating || store.taskRequestPending} onDelete={store.deleteTask} />}
          </div>
          <details className="task-execution-section" open={["completed", "failed", "cancelled", "waiting_for_user"].includes(task.state)}>
            <summary>Подробности, ревью и управление задачей</summary>
            <TaskCard task={task} busy={store.generating || store.taskRequestPending}
              onResume={store.resumeTask} onCancel={store.cancelTask} onSave={store.saveTask}
              onDelete={store.deleteTask} onReview={store.reviewTask} onInspect={store.setFocusedTaskId} />
          </details>
        </div>
      )}
    </section>
  );
}