import { useState } from "react";
import { ListChecks, Loader2, Play, RefreshCw, Sparkles } from "lucide-react";
import type { Task, TaskPlan } from "../types";
import { TaskCard, STATE_CONFIG } from "./TaskCard";
import { useLocale } from "../lib/locale";
import "./TaskPanel.css";

interface Props {
  tasks: Task[];
  busy: boolean;
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
  onRecover: (id: string) => Promise<Task | null>;
  onInspect: (id: string) => void;
}

export default function TaskPanel(props: Props) {
  const [goal, setGoal] = useState("");
  const [planning, setPlanning] = useState(false);
  const { t } = useLocale();

  const handlePlanOnly = async () => {
    const text = goal.trim();
    if (!text || props.busy || planning) return;
    setPlanning(true);
    try {
      const plan = await props.onPlan(text);
      if (plan) {
        const task = await props.onCreate(text, plan);
        if (task) setGoal("");
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
      if (!plan) return;
      const task = await props.onStart(text, plan);
      if (task) setGoal("");
    } finally {
      setPlanning(false);
    }
  };

  return (
    <section className="task-panel" aria-label={t("ui.task.aria")}>
      <header className="task-panel-header">
        <div className="task-panel-title-group">
          <ListChecks size={15} strokeWidth={2} />
          <span>{t("ui.task.panel")}</span>
          {props.tasks.length > 0 && (
            <span className="task-count-pill">{props.tasks.length}</span>
          )}
        </div>
        <button
          className="task-btn-icon"
          title={t("ui.task.refresh")}
          aria-label={t("ui.task.refresh")}
          onClick={() => void props.onRefresh()}
        >
          <RefreshCw size={13} strokeWidth={1.8} />
        </button>
      </header>

      <div className="task-creator">
        <textarea
          aria-label={t("ui.task.goal_aria")}
          className="task-goal-input"
          value={goal}
          maxLength={16000}
          disabled={props.busy || planning}
          rows={3}
          placeholder={t("ui.task.goal_placeholder")}
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
            title={t("ui.task.plan_title")}
            onClick={() => void handlePlanOnly()}
          >
            {planning ? (
              <Loader2 size={13} className="spin" />
            ) : (
              <Sparkles size={13} strokeWidth={1.8} />
            )}
            <span>{t("ui.task.plan")}</span>
          </button>

          <button
            type="button"
            className="task-btn primary"
            disabled={props.busy || planning || !goal.trim()}
            title={t("ui.task.run_title")}
            onClick={() => void handlePlanAndExecute()}
          >
            <Play size={13} fill="currentColor" strokeWidth={1.8} />
            <span>{t("ui.task.run")}</span>
          </button>
        </div>
      </div>

      <div className="task-list-section">
        {props.tasks.length === 0 ? (
          <div className="task-empty-state">
            <ListChecks size={28} strokeWidth={1.4} />
            <div className="task-empty-title">{t("ui.task.none")}</div>
            <p className="task-empty-sub">
              {t("ui.task.none_sub")}
            </p>
          </div>
        ) : (
          props.tasks.map((task) => task.state !== "pending" ? (
            <button className="task-summary" key={task.id} onClick={() => props.onInspect(task.id)}>
              <span className={`task-status-badge ${task.review_recovery ? "warning" : STATE_CONFIG[task.state].tone}`}>{task.review_recovery ? t("ui.task.review_recovery") : t(STATE_CONFIG[task.state].label)}</span>
              <strong>{task.goal}</strong>
              <span className="task-summary-link">{t("ui.task.open_execution")}</span>
            </button>
          ) : (
            <TaskCard
              key={task.id}
              task={task}
              busy={props.busy}
              onResume={props.onResume}
              onCancel={props.onCancel}
              onSave={props.onSave}
              onDelete={props.onDelete}
              onReview={props.onReview}
              onRecover={props.onRecover}
              onInspect={props.onInspect}
            />
          ))
        )}
      </div>
    </section>
  );
}
