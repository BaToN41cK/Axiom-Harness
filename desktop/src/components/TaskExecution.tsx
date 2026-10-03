import { ArrowLeft, Check, Circle, FileCode2, Loader2, TriangleAlert, X } from "lucide-react";
import { TaskCard } from "./TaskCard";
import TaskDelete from "./TaskDelete";
import TaskResume from "./TaskResume";
import DiffReview from "./DiffReview";
import TaskReviewActions from "./TaskReviewActions";
import type { Task } from "../types";
import type { AxiomStore } from "../hooks/useAxiom";
import { useLocale } from "../lib/locale";

interface Props {
  task: Task | null;
  store: AxiomStore;
  onBack: () => void;
}

const LABELS: Record<Task["state"], string> = {
  pending: "ui.taskexec.state.pending", analyzing: "ui.taskexec.state.analyzing", planning: "ui.taskexec.state.planning",
  executing: "ui.taskexec.state.executing", verifying: "ui.taskexec.state.verifying", waiting_for_permission: "ui.taskexec.state.waiting_for_permission",
  waiting_for_user: "ui.taskexec.state.waiting_for_user", completed: "ui.taskexec.state.completed", failed: "ui.taskexec.state.failed", cancelled: "ui.taskexec.state.cancelled",
};

/** Human names for the W4.3 context categories shown in the budget rows. */
const BUDGET_LABELS: Record<string, string> = {
  system: "ui.taskexec.budget.system", project: "ui.taskexec.budget.project", task: "ui.taskexec.budget.task", files: "ui.taskexec.budget.files",
  tool_results: "ui.taskexec.budget.tool_results", conversation: "ui.taskexec.budget.conversation",
};


export default function TaskExecution({ task, store, onBack }: Props) {
  const { t } = useLocale();
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
    <section className="task-execution" aria-label={t("ui.taskexec.aria")}>
      <header className="task-execution-head">
        <button className="task-execution-back" onClick={onBack} title={t("ui.taskexec.back")}><ArrowLeft size={15} /> {t("ui.taskexec.chat")}</button>
        <span className="task-execution-kicker">TASK EXECUTION</span>
        {task && <span className={`task-execution-state ${task.state}`}><span />{t(LABELS[task.state])}</span>}
      </header>
      {!task ? (
        <div className="task-execution-loading"><Loader2 size={18} className="spin" /> {t("ui.taskexec.loading")}</div>
      ) : (
        <div className="task-execution-scroll">
          <div className="task-execution-title-row">
            <div><h1>{task.goal}</h1><p>{task.detail || t(LABELS[task.state])}</p></div>
            {steps.length > 0 && <strong>{progress}%</strong>}
          </div>
          {steps.length > 0 && <div className="task-execution-progress"><span style={{ width: `${progress}%` }} /></div>}
          {resumable && <TaskResume key={`${task.id}:${task.revision}`} task={task} busy={store.generating || store.taskRequestPending} onResume={store.resumeTask} />}
          {activeStep && running && <div className="task-execution-now"><Loader2 size={15} className="spin" /><div><b>{t("ui.taskexec.now")}</b><span>{activeStep.goal}</span></div></div>}
          {task.pending_tool && <div className="task-execution-warning"><TriangleAlert size={15} /><span><b>{task.state === "waiting_for_permission" ? t("ui.taskexec.tool_wait") : running ? t("ui.taskexec.tool_active") : t("ui.taskexec.tool_interrupted")}</b><code>{String(task.pending_tool.name ?? t("ui.taskexec.tool"))}</code><pre>{JSON.stringify(task.pending_tool.arguments ?? {}, null, 2)}</pre></span></div>}
          <div className="task-execution-section"><div className="task-execution-section-label">{t("ui.taskexec.plan")}</div>
            {steps.length ? <ol className="task-execution-steps">{steps.map((step) => (
              <li key={step.id} className={step.state}>
                <span className="task-execution-step-icon">{step.state === "completed" ? <Check size={13} /> : step.state === "running" && running ? <Loader2 size={13} className="spin" /> : step.state === "failed" ? <X size={13} /> : <Circle size={9} />}</span>
                <span>{step.goal}</span>{step.result && <small>{step.result}</small>}
              </li>
            ))}</ol> : <p className="task-execution-empty">{t("ui.taskexec.plan_empty")}</p>}
          </div>
          {task.changed_files.length > 0 && <div className="task-execution-section"><div className="task-execution-section-label"><FileCode2 size={13} /> {t("ui.taskexec.changed_files")}</div><div className="task-execution-files">{task.changed_files.map((file) => <code key={file}>{file}</code>)}</div></div>}
          {diffEntries.length > 0 && (
            <div className="task-execution-section">
              <div className="task-execution-section-label"><FileCode2 size={13} /> {t("ui.taskexec.diff", { n: String(diffEntries.length) })}</div>
              <div className="task-execution-review">
                {task.state === "completed" ? (task.review_status === "pending" || task.review_recovery ? (
                  <TaskReviewActions key={task.id} task={task} busy={store.generating || store.taskRequestPending} onReview={store.reviewTask} onRecover={store.recoverReview} />
                ) : (
                  <span className={`task-execution-review-state ${task.review_status}`}>{task.review_status === "accepted" ? t("ui.taskexec.accepted") : t("ui.taskexec.rejected")}</span>
                )) : <span className="task-execution-review-state pending">{t("ui.taskexec.review_pending")}</span>}
              </div>
              <DiffReview key={task.id} diffs={task.diffs} onOpenFile={(path) => void store.openWorkspaceFile(path)} />
            </div>
          )}
          {budgetRows.length > 0 && (
            <div className="task-execution-section">
              <div className="task-execution-section-label">{t("ui.taskexec.budget")}</div>
              <div className="task-execution-budgets">
                {budgetRows.map(([cat, used]) => {
                  const budget = report?.budgets?.[cat] ?? 0;
                  const pct = budget > 0 ? Math.min(100, Math.round(used / budget * 100)) : used > 0 ? 100 : 0;
                  const over = (report?.over_budget ?? []).includes(cat);
                  return (
                    <div className={`task-execution-budget${over ? " over" : ""}`} key={cat} title={`${cat}: ${used} / ${budget}`}>
                      <span className="task-execution-budget-cat">{t(BUDGET_LABELS[cat] ?? cat)}</span>
                      <span className="task-execution-budget-bar"><span style={{ width: `${pct}%` }} /></span>
                      <span className="task-execution-budget-num">{used} / {budget}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {task.commands.length > 0 && <div className="task-execution-section"><div className="task-execution-section-label">{t("ui.taskexec.commands")}</div>{task.commands.map((command, index) => <details key={index}><summary>{String(command.tool ?? "command")} · {String(command.state ?? "")} {String(command.command ?? "")}</summary><pre>{String(command.output ?? t("ui.taskexec.no_output"))}</pre></details>)}</div>}
          {task.tests.length > 0 && <div className="task-execution-section"><div className="task-execution-section-label">{t("ui.taskexec.checks")}</div>{task.tests.map((test, index) => <pre key={index} className={test.ok === true && test.executed === true ? "ok" : "error"}>{String(test.summary ?? test.error ?? JSON.stringify(test))}</pre>)}</div>}
          {task.errors.length > 0 && <div className="task-execution-error"><b>{t("ui.taskexec.error")}</b><span>{task.errors[task.errors.length - 1].message}</span></div>}
          {task.state === "completed" && <div className="task-execution-done"><Check size={15} />{task.review_recovery ? t("ui.task.review_recovery") : task.review_status === "accepted" ? t("ui.taskexec.accepted") : task.review_status === "rejected" ? t("ui.taskexec.rejected") : t("ui.taskexec.ready_review")}</div>}
          <div className="task-execution-actions">
            {store.activeTaskId === task.id && <button className="task-execution-stop" onClick={() => void store.cancelTask(task.id)}><X size={14} /> {t("ui.taskexec.stop")}</button>}
            {!running && <TaskDelete key={`${task.id}:${task.revision}`} task={task} busy={store.generating || store.taskRequestPending} onDelete={store.deleteTask} />}
          </div>
          <details className="task-execution-section" open={["completed", "failed", "cancelled", "waiting_for_user"].includes(task.state)}>
            <summary>{t("ui.taskexec.details")}</summary>
            <TaskCard task={task} busy={store.generating || store.taskRequestPending}
              onResume={store.resumeTask} onCancel={store.cancelTask} onSave={store.saveTask}
              onDelete={store.deleteTask} onReview={store.reviewTask} onRecover={store.recoverReview} onInspect={store.setFocusedTaskId} />
          </details>
        </div>
      )}
    </section>
  );
}