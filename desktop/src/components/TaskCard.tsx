import { useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Circle,
  FileCode,
  Loader2,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Square,
  Trash2,
  X,
} from "lucide-react";
import type { Task, TaskPlan, TaskPlanStep, TaskState } from "../types";

export const STATE_CONFIG: Record<
  TaskState,
  { label: string; tone: "pending" | "info" | "active" | "success" | "warning" | "error" | "muted" }
> = {
  pending: { label: "План готов к исполнению", tone: "pending" },
  analyzing: { label: "Анализ проекта…", tone: "info" },
  planning: { label: "Формирование плана…", tone: "info" },
  executing: { label: "Выполнение шагов…", tone: "active" },
  verifying: { label: "Проверка результатов…", tone: "warning" },
  waiting_for_permission: { label: "Ожидает разрешения", tone: "warning" },
  waiting_for_user: { label: "Требуется решение", tone: "warning" },
  completed: { label: "Завершена успешно", tone: "success" },
  failed: { label: "Ошибка выполнения", tone: "error" },
  cancelled: { label: "Остановлена", tone: "muted" },
};

interface TaskCardProps {
  task: Task;
  busy: boolean;
  activeId: string | null;
  onResume: (id: string, acknowledge: boolean) => Promise<Task | null>;
  onCancel: (id: string) => Promise<boolean>;
  onSave: (
    id: string,
    updates: { goal?: string; plan?: TaskPlan; state?: string },
  ) => Promise<Task | null>;
  onDelete: (id: string) => Promise<boolean>;
  onReview: (id: string, decision: "accept" | "reject") => Promise<Task | null>;
}

export function TaskCard(props: TaskCardProps) {
  const { task, busy, activeId, onResume, onCancel, onSave, onDelete, onReview } = props;
  const [acknowledged, setAcknowledged] = useState(false);
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [editStepText, setEditStepText] = useState("");
  const [addingStep, setAddingStep] = useState(false);
  const [newStepGoal, setNewStepGoal] = useState("");

  const runningState = ["analyzing", "planning", "executing", "waiting_for_permission", "verifying"].includes(task.state);
  const isActive = runningState && (activeId === task.id || (busy && task.state === "executing"));
  const stateMeta = STATE_CONFIG[task.state] || { label: task.state, tone: "muted" };

  const steps = task.plan?.steps ?? [];
  const completedSteps = steps.filter((s) => s.state === "completed").length;
  const progressPercent = steps.length > 0 ? Math.round((completedSteps / steps.length) * 100) : 0;
  const interrupted =
    Boolean(task.pending_tool) || steps.some((step) => step.state === "running");

  const updateSteps = (newSteps: TaskPlanStep[]) => {
    if (!task.plan) return;
    const updatedPlan: TaskPlan = { ...task.plan, steps: newSteps };
    void onSave(task.id, { plan: updatedPlan });
  };

  const handleToggleStep = (stepId: string) => {
    if (isActive) return;
    const newSteps = steps.map((s) => {
      if (s.id !== stepId) return s;
      const nextState: TaskPlanStep["state"] =
        s.state === "completed" ? "pending" : "completed";
      return { ...s, state: nextState };
    });
    updateSteps(newSteps);
  };

  const handleStartEditStep = (step: TaskPlanStep) => {
    if (isActive) return;
    setEditingStepId(step.id);
    setEditStepText(step.goal);
  };

  const handleSaveEditStep = (stepId: string) => {
    if (!editStepText.trim()) return;
    const newSteps = steps.map((s) =>
      s.id === stepId ? { ...s, goal: editStepText.trim() } : s,
    );
    updateSteps(newSteps);
    setEditingStepId(null);
  };

  const handleDeleteStep = (stepId: string) => {
    if (isActive) return;
    const newSteps = steps.filter((s) => s.id !== stepId);
    updateSteps(newSteps);
  };

  const handleAddNewStep = () => {
    if (!newStepGoal.trim() || !task.plan) return;
    const newStep: TaskPlanStep = {
      id: `step-${Date.now().toString(36)}`,
      goal: newStepGoal.trim(),
      tools: [],
      done_when: "Выполнено",
      state: "pending",
      result: "",
    };
    updateSteps([...steps, newStep]);
    setNewStepGoal("");
    setAddingStep(false);
  };

  return (
    <article className={`task-card ${isActive ? "active" : ""} ${task.state}`}>
      <div className="task-card-header">
        <span className={`task-status-badge ${stateMeta.tone}`}>
          {task.state === "completed" && <CheckCircle2 size={12} strokeWidth={2.4} />}
          {isActive && <Loader2 size={12} className="spin" />}
          {(task.state === "waiting_for_user" || task.state === "waiting_for_permission") && <AlertTriangle size={12} />}
          <span>{stateMeta.label}</span>
        </span>

        <div className="task-card-header-actions">
          {!isActive && (
            <button
              className="task-btn-icon danger"
              title="Удалить задачу"
              aria-label="Удалить задачу"
              onClick={() => void onDelete(task.id)}
            >
              <Trash2 size={13} strokeWidth={1.8} />
            </button>
          )}
        </div>
      </div>

      <h4 className="task-goal">{task.goal}</h4>

      {task.detail && <p className="task-detail-hint">{task.detail}</p>}

      {task.pending_tool && (
        <div className={`task-pending-tool ${task.state === "waiting_for_permission" ? "waiting" : ""}`}>
          <strong>
            {task.state === "waiting_for_permission" ? "Запрос разрешения" : "Активный инструмент"}
            {typeof task.pending_tool.name === "string" ? ` · ${task.pending_tool.name}` : ""}
          </strong>
          {Boolean(task.pending_tool.arguments) && Object.keys(task.pending_tool.arguments as object).length > 0 && (
            <pre>{JSON.stringify(task.pending_tool.arguments, null, 2)}</pre>
          )}
        </div>
      )}

      {steps.length > 0 && (
        <div className="task-progress-wrap">
          <div className="task-progress-bar">
            <span
              className={`task-progress-fill ${task.state === "completed" ? "completed" : ""}`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <span className="task-progress-label">
            {completedSteps} из {steps.length} шагов ({progressPercent}%)
          </span>
        </div>
      )}

      {steps.length > 0 ? (
        <div className="task-plan-section">
          <div className="task-plan-title">План выполнения:</div>
          <ul className="task-steps-list">
            {steps.map((step, idx) => {
              const isCompleted = step.state === "completed";
              const isRunning = step.state === "running";
              const isFailed = step.state === "failed";
              const isEditing = editingStepId === step.id;

              return (
                <li
                  key={step.id}
                  className={`task-step-item ${step.state} ${isRunning ? "running" : ""}`}
                >
                  <button
                    type="button"
                    className={`task-step-checkbox ${step.state}`}
                    title={
                      isCompleted
                        ? "Шаг выполнен (клик — отменить)"
                        : "Клик — пометить выполненным"
                    }
                    disabled={isActive}
                    onClick={() => handleToggleStep(step.id)}
                  >
                    {isCompleted && <Check size={12} strokeWidth={2.5} />}
                    {isRunning && <Loader2 size={12} className="spin" />}
                    {isFailed && <X size={12} strokeWidth={2.2} />}
                    {!isCompleted && !isRunning && !isFailed && <Circle size={10} />}
                  </button>

                  <div className="task-step-body">
                    {isEditing ? (
                      <div className="task-step-edit-form">
                        <input
                          type="text"
                          className="task-step-input"
                          value={editStepText}
                          autoFocus
                          onChange={(e) => setEditStepText(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleSaveEditStep(step.id);
                            if (e.key === "Escape") setEditingStepId(null);
                          }}
                        />
                        <button
                          type="button"
                          className="task-btn mini primary"
                          onClick={() => handleSaveEditStep(step.id)}
                        >
                          <Check size={12} />
                        </button>
                        <button
                          type="button"
                          className="task-btn mini ghost"
                          onClick={() => setEditingStepId(null)}
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ) : (
                      <div className="task-step-content">
                        <span className="task-step-idx">{idx + 1}.</span>
                        <span
                          className={`task-step-text ${isCompleted ? "done" : ""}`}
                          title="Кликните на карандаш для редактирования"
                        >
                          {step.goal}
                        </span>
                      </div>
                    )}

                    {step.result && (
                      <details className="task-step-result-details">
                        <summary>Результат шага</summary>
                        <pre>{step.result}</pre>
                      </details>
                    )}
                  </div>

                  {!isActive && !isEditing && (
                    <div className="task-step-actions">
                      <button
                        type="button"
                        className="task-btn-icon"
                        title="Редактировать формулировку шага"
                        onClick={() => handleStartEditStep(step)}
                      >
                        <Pencil size={11} strokeWidth={1.8} />
                      </button>
                      <button
                        type="button"
                        className="task-btn-icon danger"
                        title="Удалить шаг из плана"
                        onClick={() => handleDeleteStep(step.id)}
                      >
                        <Trash2 size={11} strokeWidth={1.8} />
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>

          {!isActive && (
            <div className="task-add-step-wrap">
              {addingStep ? (
                <div className="task-add-step-form">
                  <input
                    type="text"
                    className="task-step-input"
                    placeholder="Например: Добавить проверку входных данных..."
                    value={newStepGoal}
                    autoFocus
                    onChange={(e) => setNewStepGoal(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleAddNewStep();
                      if (e.key === "Escape") setAddingStep(false);
                    }}
                  />
                  <button
                    type="button"
                    className="task-btn mini primary"
                    disabled={!newStepGoal.trim()}
                    onClick={handleAddNewStep}
                  >
                    Добавить
                  </button>
                  <button
                    type="button"
                    className="task-btn mini ghost"
                    onClick={() => setAddingStep(false)}
                  >
                    Отмена
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="task-btn-text"
                  onClick={() => setAddingStep(true)}
                >
                  <Plus size={12} strokeWidth={2} />
                  <span>Добавить шаг в план</span>
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="task-no-plan-hint">
          План выполнения ещё не сформирован.
        </div>
      )}
      {task.changed_files.length > 0 && (
        <div className="task-changed-files">
          <div className="task-meta-label">
            <FileCode size={12} />
            <span>Изменённые файлы ({task.changed_files.length}):</span>
          </div>
          <div className="task-files-tags">
            {task.changed_files.map((file) => (
              <span key={file} className="task-file-tag" title={file}>
                {file}
              </span>
            ))}
          </div>
        </div>
      )}

      {Object.keys(task.diffs ?? {}).length > 0 && (
        <details className="task-details-box review-diff" open={task.state === "completed" && task.review_status === "pending"}>
          <summary>Ревью изменений ({Object.keys(task.diffs).length} файлов) · {task.review_status === "accepted" ? "принято" : task.review_status === "rejected" ? "отклонено" : "ожидает решения"}</summary>
          {Object.entries(task.diffs).map(([path, diff]) => (
            <details key={path} className="task-diff-file" open>
              <summary>{path}</summary>
              <pre>{diff}</pre>
            </details>
          ))}
        </details>
      )}

      {task.commands?.length > 0 && (
        <details className="task-details-box tests">
          <summary>Команды задачи ({task.commands.length})</summary>
          {task.commands.map((command, index) => (
            <div className="task-verification-item" key={`${String(command.tool)}-${index}`}>
              <strong>{String(command.tool)} · {String(command.state)}</strong>
              {typeof command.command === "string" && <code>{command.command}</code>}
              {typeof command.output === "string" && <pre>{command.output}</pre>}
            </div>
          ))}
        </details>
      )}

      {task.active_processes?.length > 0 && (
        <details className="task-details-box tests" open={isActive}>
          <summary>Дочерние процессы ({task.active_processes.length})</summary>
          {task.active_processes.map((process, index) => (
            <div className="task-verification-item" key={`${String(process.pid)}-${index}`}>
              <strong>PID {String(process.pid)} · {String(process.state)}</strong>
              {typeof process.command === "string" && <code>{process.command}</code>}
            </div>
          ))}
        </details>
      )}

      {task.errors.length > 0 && (
        <details className="task-details-box errors">
          <summary>Ошибки выполнения ({task.errors.length})</summary>
          {task.errors.map((error, index) => (
            <div className="task-error-item" key={`${error.type}-${error.step_id ?? "task"}-${index}`}>
              <strong>{error.type}{error.tool ? ` · ${error.tool}` : ""}</strong>
              <p>{error.message}</p>
              {error.command && <code>{error.command}{error.exit_code !== null ? ` (exit ${error.exit_code})` : ""}</code>}
              {(error.stderr || error.stdout) && <pre>{error.stderr || error.stdout}</pre>}
            </div>
          ))}
        </details>
      )}

      {task.tests.length > 0 && (
        <details className="task-details-box tests">
          <summary>Результаты проверки ({task.tests.length})</summary>
          {task.tests.map((report, index) => (
            <div className="task-verification-item" key={`verification-${index}`}>
              <strong className={report.ok === true && report.executed === true ? "passed" : "failed"}>
                {report.ok === true && report.executed === true ? "Проверка пройдена" : "Проверка не пройдена"}
              </strong>
              {typeof report.summary === "string" && <p>{report.summary}</p>}
              {typeof report.error === "string" && <p className="verification-error">Причина: {report.error}</p>}
              {Boolean(report.checks) && <pre>{JSON.stringify(report.checks, null, 2)}</pre>}
            </div>
          ))}
        </details>
      )}

      <div className="task-card-footer">
        {isActive ? (
          <button
            type="button"
            className="task-btn danger"
            onClick={() => void onCancel(task.id)}
          >
            <Square size={13} fill="currentColor" />
            <span>Остановить</span>
          </button>
        ) : task.state === "completed" ? (
          <div className="task-completed-note">
            <CheckCircle2 size={14} className="text-success" />
            <span>{task.review_status === "pending" ? "Проверка пройдена · результат готов к ревью" : task.review_status === "accepted" ? "Изменения приняты" : "Изменения отклонены"}</span>
            {task.review_status === "pending" && (
              <>
                <button type="button" className="task-btn mini primary" onClick={() => void onReview(task.id, "accept")}>
                  <Check size={12} /><span>Принять</span>
                </button>
                <button type="button" className="task-btn mini danger" onClick={() => void onReview(task.id, "reject")}>
                  <X size={12} /><span>Отклонить</span>
                </button>
              </>
            )}
            <button
              type="button"
              className="task-btn mini ghost"
              title="Запустить повторно"
              onClick={() => void onResume(task.id, true)}
            >
              <RotateCcw size={12} />
              <span>Повторить</span>
            </button>
          </div>
        ) : (
          <div className="task-footer-actions">
            {interrupted && (
              <label className="task-acknowledge-check">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                />
                <span>Подтверждаю состояние файлов после прерывания</span>
              </label>
            )}
            <button
              type="button"
              className="task-btn primary"
              disabled={busy || (interrupted && !acknowledged)}
              onClick={() => {
                void onResume(task.id, acknowledged);
                setAcknowledged(false);
              }}
            >
              <Play size={13} fill="currentColor" />
              <span>
                {task.state === "pending"
                  ? "Приступить к реализации"
                  : "Продолжить выполнение"}
              </span>
            </button>
          </div>
        )}
      </div>
    </article>
  );
}
