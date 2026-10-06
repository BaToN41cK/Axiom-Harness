import { useState } from "react";
import {
  ListChecks,
  Loader2,
  Pencil,
  Play,
  Plus,
  Save,
  Trash2,
  X,
} from "lucide-react";
import type { Task } from "../types";
import { useLocale } from "../lib/locale";

/** Coarse task status for the left-panel list (draft / running / terminal). */
export type TaskStatus = "draft" | "running" | "completed" | "failed" | "cancelled";

export function taskStatus(task: Task): TaskStatus {
  switch (task.state) {
    case "pending":
      return "draft";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return "running";
  }
}

interface TaskDraft {
  title: string;
  description: string;
}

interface Props {
  tasks: Task[];
  focusedTaskId: string | null;
  busy: boolean;
  draft: TaskDraft;
  onDraftChange: (draft: TaskDraft) => void;
  onCreate: (goal: string, description: string) => Promise<Task | null>;
  onSave: (id: string, updates: { goal?: string; description?: string }) => Promise<Task | null>;
  onDelete: (id: string) => Promise<boolean>;
  onRun: (id: string) => Promise<Task | null>;
  onSelect: (id: string) => void;
}

/** Left-panel task workspace: prepare drafts, edit, save, select and run. */
export default function TaskWorkspace(props: Props) {
  const { t } = useLocale();
  const { tasks, focusedTaskId, busy, draft, onDraftChange, onCreate, onSave, onDelete, onRun, onSelect } = props;
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(false);

  const canSubmit = draft.title.trim().length > 0 && !busy && !pending;

  const startCreate = () => {
    setCreating(true);
    setEditingId(null);
    onDraftChange({ title: "", description: "" });
  };

  const startEdit = (task: Task) => {
    setEditingId(task.id);
    setCreating(false);
    onDraftChange({ title: task.goal, description: task.description ?? "" });
  };

  const closeEditor = () => {
    setCreating(false);
    setEditingId(null);
    onDraftChange({ title: "", description: "" });
  };

  const submit = async () => {
    if (!canSubmit) return;
    setPending(true);
    try {
      if (editingId) {
        await onSave(editingId, {
          goal: draft.title.trim(),
          description: draft.description,
        });
      } else {
        const task = await onCreate(draft.title.trim(), draft.description);
        if (task) onSelect(task.id);
      }
      closeEditor();
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="task-workspace">
      <div className="side-subhead">
        <ListChecks size={12} strokeWidth={1.8} />
        <span>{t("ui.tabs.tasks")}</span>
        {tasks.length > 0 && <span className="ws-nav-count">{tasks.length}</span>}
        <button
          className="icon-btn tiny"
          title={t("ui.task.new")}
          aria-label={t("ui.task.new")}
          onClick={creating ? closeEditor : startCreate}
        >
          {creating ? <X size={11} strokeWidth={2} /> : <Plus size={11} strokeWidth={2} />}
        </button>
      </div>

      {(creating || editingId) && (
        <div className="task-workspace-editor">
          <input
            className="task-workspace-title"
            value={draft.title}
            maxLength={16000}
            placeholder={t("ui.task.title_placeholder")}
            aria-label={t("ui.task.title_label")}
            onChange={(event) => onDraftChange({ ...draft, title: event.target.value })}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                void submit();
              }
            }}
          />
          <textarea
            className="task-workspace-desc"
            value={draft.description}
            placeholder={t("ui.task.description_placeholder")}
            aria-label={t("ui.task.description_label")}
            rows={3}
            onChange={(event) => onDraftChange({ ...draft, description: event.target.value })}
          />
          <div className="task-workspace-actions">
            <button className="mini-btn" onClick={closeEditor} disabled={pending}>
              {t("ui.common.cancel")}
            </button>
            <button
              className="mini-btn"
              disabled={!canSubmit}
              onClick={() => void submit()}
            >
              {pending ? (
                <Loader2 size={11} className="spin" />
              ) : editingId ? (
                <Save size={11} />
              ) : (
                <Plus size={11} />
              )}
              <span>{editingId ? t("ui.task.save_draft") : t("ui.task.create")}</span>
            </button>
          </div>
        </div>
      )}

      <div className="ws-task-list">
        {tasks.length === 0 && !creating && !editingId && (
          <div className="chat-list-empty">{t("ui.task.none")}</div>
        )}
        {tasks.map((task) => {
          const status = taskStatus(task);
          const active = task.id === focusedTaskId;
          return (
            <div
              key={task.id}
              className={"ws-task-item" + (active ? " active" : "")}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(task.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(task.id);
                }
              }}
              title={task.goal}
            >
              <span className={"ws-task-state " + status} />
              <span className="ws-task-goal">{task.goal}</span>
              {status === "running" && <Loader2 size={10} className="spin" />}
              {!active && status !== "running" && (
                <span className="ws-task-actions">
                  <button
                    className="ws-task-mini"
                    title={t("ui.task.run")}
                    aria-label={t("ui.task.run")}
                    disabled={busy}
                    onClick={(event) => {
                      event.stopPropagation();
                      void onRun(task.id);
                    }}
                  >
                    <Play size={11} strokeWidth={2} />
                  </button>
                  <button
                    className="ws-task-mini"
                    title={t("ui.common.edit")}
                    aria-label={t("ui.common.edit")}
                    disabled={busy}
                    onClick={(event) => {
                      event.stopPropagation();
                      startEdit(task);
                    }}
                  >
                    <Pencil size={11} strokeWidth={2} />
                  </button>
                  <button
                    className="ws-task-mini danger"
                    title={t("ui.taskcard.delete")}
                    aria-label={t("ui.taskcard.delete")}
                    disabled={busy}
                    onClick={(event) => {
                      event.stopPropagation();
                      void onDelete(task.id);
                    }}
                  >
                    <Trash2 size={11} strokeWidth={2} />
                  </button>
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
