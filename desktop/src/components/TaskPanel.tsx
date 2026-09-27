import { useState } from "react";
import { ListChecks, Loader2, Play, RefreshCw, Sparkles } from "lucide-react";
import type { Task, TaskPlan } from "../types";
import { TaskCard } from "./TaskCard";
import "./TaskPanel.css";

interface Props {
  tasks: Task[];
  busy: boolean;
  activeId: string | null;
  onStart: (goal: string, plan?: TaskPlan) => Promise<Task | null>;
  onResume: (id: string, acknowledge: boolean) => Promise<Task | null>;
  onCancel: (id: string) => Promise<boolean>;
  onRefresh: () => Promise<void>;
  onPlan: (goal: string) => Promise<TaskPlan | null>;
  onCreate: (goal: string, plan?: TaskPlan) => Promise<Task | null>;
  onSave: (
    id: string,
    updates: { goal?: string; plan?: TaskPlan; state?: string },
  ) => Promise<Task | null>;
  onDelete: (id: string) => Promise<boolean>;
  onReview: (id: string, decision: "accept" | "reject") => Promise<Task | null>;
}

export default function TaskPanel(props: Props) {
  const [goal, setGoal] = useState("");
  const [planning, setPlanning] = useState(false);

  const handlePlanOnly = async () => {
    const text = goal.trim();
    if (!text || props.busy || planning) return;
    setPlanning(true);
    try {
      const plan = await props.onPlan(text);
      if (plan) {
        await props.onCreate(text, plan);
        setGoal("");
      }
    } finally {
      setPlanning(false);
    }
  };

  const handlePlanAndExecute = async () => {
    const text = goal.trim();
    if (!text || props.busy || planning) return;
    setPlanning(true);
    try {
      const plan = await props.onPlan(text);
      await props.onStart(text, plan ?? undefined);
      setGoal("");
    } finally {
      setPlanning(false);
    }
  };

  return (
    <section className="task-panel" aria-label="Задачи">
      <header className="task-panel-header">
        <div className="task-panel-title-group">
          <ListChecks size={15} strokeWidth={2} />
          <span>Задачник</span>
          {props.tasks.length > 0 && (
            <span className="task-count-pill">{props.tasks.length}</span>
          )}
        </div>
        <button
          className="task-btn-icon"
          title="Обновить задачи"
          aria-label="Обновить задачи"
          onClick={() => void props.onRefresh()}
        >
          <RefreshCw size={13} strokeWidth={1.8} />
        </button>
      </header>

      <div className="task-creator">
        <textarea
          aria-label="Цель задачи"
          className="task-goal-input"
          value={goal}
          maxLength={16000}
          disabled={props.busy || planning}
          rows={3}
          placeholder="Опишите задачу (например: «Исправить ошибку валидации формы и добавить тесты»)..."
          onChange={(event) => setGoal(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              void handlePlanAndExecute();
            }
          }}
        />

        <div className="task-creator-actions">
          <button
            type="button"
            className="task-btn secondary"
            disabled={props.busy || planning || !goal.trim()}
            title="ИИ сформирует пошаговый план действий в задачнике, который можно отредактировать перед запуском"
            onClick={() => void handlePlanOnly()}
          >
            {planning ? (
              <Loader2 size={13} className="spin" />
            ) : (
              <Sparkles size={13} strokeWidth={1.8} />
            )}
            <span>Спланировать задачу</span>
          </button>

          <button
            type="button"
            className="task-btn primary"
            disabled={props.busy || planning || !goal.trim()}
            title="Спланировать и сразу приступить к выполнению (Ctrl+Enter)"
            onClick={() => void handlePlanAndExecute()}
          >
            <Play size={13} fill="currentColor" strokeWidth={1.8} />
            <span>Выполнить</span>
          </button>
        </div>
      </div>

      <div className="task-list-section">
        {props.tasks.length === 0 ? (
          <div className="task-empty-state">
            <ListChecks size={28} strokeWidth={1.4} />
            <div className="task-empty-title">Задач пока нет</div>
            <p className="task-empty-sub">
              Напишите цель выше: ИИ декомпозирует её на конкретные шаги, выдаст чеклист,
              после чего последовательно реализует каждый шаг и отметит галочкой.
            </p>
          </div>
        ) : (
          props.tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              busy={props.busy}
              activeId={props.activeId}
              onResume={props.onResume}
              onCancel={props.onCancel}
              onSave={props.onSave}
              onDelete={props.onDelete}
          onReview={props.onReview}
            />
          ))
        )}
      </div>
    </section>
  );
}
