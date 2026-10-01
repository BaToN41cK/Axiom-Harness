import { useMemo, useState } from "react";
import {
  Camera,
  CircleCheck,
  CircleHelp,
  FileMinus,
  FilePen,
  FilePlus2,
  FolderGit2,
  GitBranch,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import type { ProjectInfo } from "../types";

interface GitState {
  ok: boolean;
  content: string;
  error: string | null;
}

interface Props {
  project: ProjectInfo | null;
  status: GitState | null;
  log: GitState | null;
  onRefresh: () => void;
  onCheckpoint: () => void;
  onRollback: () => void;
}

/** One real change of `git status --short`: letter + path. */
interface GitChange {
  letter: string;
  path: string;
}

/**
 * Parse the real `git status --short` output the backend already provides.
 * `XY path` — X is the index state, Y is the worktree state; the letter shown
 * is the worktree one when set, otherwise the index one. Nothing is invented.
 */
function parseChanges(raw: string | null | undefined): GitChange[] {
  if (!raw) return [];
  const out: GitChange[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("##") || line.trim().length < 3) continue;
    const x = line[0];
    const y = line[1];
    const path = line.slice(3).trim().replace(/"/g, "");
    if (!path) continue;
    out.push({ letter: y !== " " ? y : x, path: path.replace(/\\/g, "/") });
  }
  return out;
}

const LETTER_TITLE: Record<string, string> = {
  M: "изменён",
  A: "новый (в индексе)",
  "?": "не отслеживается",
  D: "удалён",
  R: "переименован",
  C: "скопирован",
  U: "конфликт слияния",
};

/** Letter badge of one change — colour by real Git semantics. */
function ChangeBadge({ letter }: { letter: string }) {
  const cls =
    letter === "?"
      ? "untracked"
      : letter === "D"
        ? "deleted"
        : letter === "M"
          ? "modified"
          : "added";
  return (
    <span className={"gp-badge " + cls} title={LETTER_TITLE[letter] ?? letter}>
      {letter}
    </span>
  );
}

/** Change group with a titled list of paths. */
function ChangeGroup({
  icon,
  title,
  changes,
}: {
  icon: React.ReactNode;
  title: string;
  changes: GitChange[];
}) {
  if (changes.length === 0) return null;
  return (
    <div className="gp-group">
      <div className="gp-group-title">
        {icon}
        <span>
          {title} ({changes.length})
        </span>
      </div>
      {changes.map((c) => (
        <div key={c.path} className="gp-row" title={c.path}>
          <ChangeBadge letter={c.letter} />
          <span className="gp-path">{c.path}</span>
        </div>
      ))}
    </div>
  );
}

/** Empty state when the workspace is not a Git repository. */
function EmptyState({ title, note }: { title: string; note: string }) {
  return (
    <div className="git-empty gp-empty">
      <FolderGit2 size={22} strokeWidth={1.5} />
      <div className="gp-empty-title">{title}</div>
      <div className="gp-empty-note">{note}</div>
    </div>
  );
}

/** Git panel: branch / status / log (§17). Read-only facts from the backend. */
export default function GitPanel(props: Props) {
  const { project, status, log, onRefresh, onCheckpoint, onRollback } = props;
  const changes = useMemo(() => parseChanges(status?.ok ? status.content : null), [status]);
  const [confirmRollback, setConfirmRollback] = useState(false);

  // Global Chat: no project → no git state to show. Keep an explicit empty
  // state so the tab never looks broken/blank.
  if (!project) {
    return (
      <section className="gitpanel">
        <EmptyState
          title="Git недоступен"
          note="Git-панель появится, когда будет выбрана папка проекта."
        />
      </section>
    );
  }
  if (!project.git) {
    return (
      <section className="gitpanel">
        <EmptyState
          title="Папка не является git-репозиторием"
          note="Axiom показывает ветку, изменения и историю только для проектов под git."
        />
      </section>
    );
  }

  const modified = changes.filter((c) => c.letter === "M");
  const added = changes.filter((c) => c.letter === "A");
  const deleted = changes.filter((c) => c.letter === "D");
  const untracked = changes.filter((c) => c.letter === "?");
  const other = changes.filter((c) => !["M", "A", "D", "?"].includes(c.letter));

  return (
    <section className="gitpanel">
      <div className="ex-head">
        <GitBranch size={13} strokeWidth={1.8} />
        <span className="ex-title">{project.branch ?? "git"}</span>
        <span className="gp-count">
          {changes.length > 0 ? `${changes.length} изм.` : "чисто"}
        </span>
        <button className="icon-btn tiny" title="Обновить" onClick={onRefresh}>
          <RefreshCw size={12} strokeWidth={1.8} />
        </button>
        <button className="icon-btn tiny" title="Создать снимок" onClick={onCheckpoint}>
          <Camera size={12} strokeWidth={1.8} />
        </button>
        <button className="icon-btn tiny" title="Откат к снимку" onClick={() => setConfirmRollback(true)}>
          <RotateCcw size={12} strokeWidth={1.8} />
        </button>
      </div>

      {confirmRollback && (
        <div className="gp-rollback-confirm">
          <span>Откатить рабочее дерево к последнему снимку? Несохранённые изменения будут потеряны.</span>
          <button
            className="mini-btn danger"
            onClick={() => {
              setConfirmRollback(false);
              onRollback();
            }}
          >
            Откатить
          </button>
          <button className="mini-btn" onClick={() => setConfirmRollback(false)}>
            Отмена
          </button>
        </div>
      )}

      {changes.length === 0 && (
        <div className="gp-clean">
          <CircleCheck size={20} strokeWidth={1.6} />
          <span>Рабочее дерево чистое</span>
        </div>
      )}

      <ChangeGroup icon={<FilePen size={12} strokeWidth={1.8} />} title="Изменённые" changes={modified} />
      <ChangeGroup icon={<FilePlus2 size={12} strokeWidth={1.8} />} title="Новые" changes={added} />
      <ChangeGroup icon={<CircleHelp size={12} strokeWidth={1.8} />} title="Не отслеживаются" changes={untracked} />
      <ChangeGroup icon={<FileMinus size={12} strokeWidth={1.8} />} title="Удалённые" changes={deleted} />
      <ChangeGroup icon={<GitBranch size={12} strokeWidth={1.8} />} title="Другие" changes={other} />

      {log?.ok && log.content && (
        <div className="gp-log">
          <div className="gp-group-title">
            <GitBranch size={12} strokeWidth={1.8} />
            <span>История</span>
          </div>
          <pre className="git-log">{log.content}</pre>
        </div>
      )}
    </section>
  );
}
