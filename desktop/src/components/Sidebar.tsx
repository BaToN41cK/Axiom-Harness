import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Check, Clock, Cpu, FolderOpen, ListChecks, Loader2, MessageSquarePlus, Pencil, Search, Settings2, Trash2, X } from "lucide-react";
import type { Conversation, ModelInfo, ProjectInfo, Task } from "../types";
import { useLocale } from "../lib/locale";
import { plural } from "../lib/i18n";
import { playUiSound } from "../lib/sound";
import { STATE_CONFIG } from "./TaskCard";

interface Props {
  open: boolean;
  drawer: boolean;
  width: number;
  onWidthChange: (width: number) => void;
  onWidthCommit: (width: number) => void;
  chats: Conversation[];
  totalChats: number;
  activeChatId: string | null;
  search: string;
  onSearch: (value: string) => void;
  onNewChat: () => void;
  onOpenChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onRenameChat: (id: string, title: string) => void;
  onDeleteAllChats: () => Promise<void>;
  onOpenSettings: () => void;
  onOpenModels: () => void;
  onClose: () => void;
  activeModel: ModelInfo | null;
  /** Main-task workspace: projects + tasks navigation (left rail, §4). */
  workspace: { current: ProjectInfo | null; recent: ProjectInfo[]; pinned: ProjectInfo[] } | null;
  onOpenWorkspaceDialog: () => void;
  onSwitchWorkspace: (path: string) => void;
  onClearWorkspace: () => void;
  tasks: Task[];
  focusedTaskId: string | null;
  onInspectTask: (id: string) => void;
  onOpenTaskPanel: () => void;
}

interface Group {
  key: "today" | "yesterday" | "week" | "older";
  items: Conversation[];
}

/** Real timestamps, real day buckets (today / yesterday / week / older). */
function groupChats(chats: Conversation[]): Group[] {
  const now = Date.now() / 1000;
  const dayStart = new Date().setHours(0, 0, 0, 0) / 1000;
  const groups: Record<Group["key"], Conversation[]> = {
    today: [],
    yesterday: [],
    week: [],
    older: [],
  };
  for (const chat of chats) {
    const stamp = chat.updatedAt;
    if (stamp >= dayStart) groups.today.push(chat);
    else if (stamp >= dayStart - 86400) groups.yesterday.push(chat);
    else if (stamp >= now - 7 * 86400) groups.week.push(chat);
    else groups.older.push(chat);
  }
  return (Object.keys(groups) as Group["key"][]).filter((key) => groups[key].length > 0)
    .map((key) => ({ key, items: groups[key] }));
}

export default function Sidebar(props: Props) {
  const {
    open,
    drawer,
    width,
    onWidthChange,
    onWidthCommit,
    chats,
    totalChats,
    activeChatId,
    search,
    onSearch,
    onNewChat,
    onOpenChat,
    onDeleteChat,
    onDeleteAllChats,
    onRenameChat,
    onOpenSettings,
    onOpenModels,
    onClose,
    activeModel,
    workspace,
    onOpenWorkspaceDialog,
    onSwitchWorkspace,
    onClearWorkspace,
    tasks,
    focusedTaskId,
    onInspectTask,
    onOpenTaskPanel,
  } = props;
  const { t, locale, strings } = useLocale();

  /** Left-rail section: projects + tasks navigation, or chat history. */
  const [section, setSection] = useState<"work" | "chats">("work");
  const pickSection = (next: typeof section) => {
    if (section !== next) playUiSound("panel");
    setSection(next);
  };

  const dragging = useRef(false);
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => { if (panelRef.current) panelRef.current.inert = !open; }, [open]);
  const lastWidth = useRef(width);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  useEffect(() => {
    const onMove = (event: MouseEvent) => {
      if (!dragging.current) return;
      const next = Math.min(420, Math.max(200, event.clientX));
      lastWidth.current = next;
      onWidthChange(next);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.classList.remove("resizing");
      onWidthCommit(lastWidth.current);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [onWidthChange, onWidthCommit]);

  const startDrag = useCallback(() => {
    dragging.current = true;
    document.body.classList.add("resizing");
  }, []);

  const commitRename = (id: string) => {
    const title = draftTitle.trim();
    setRenaming(null);
    if (title) onRenameChat(id, title);
  };

  const groups = groupChats(chats);

  return (
    <>
      {drawer && open && <div className="sidebar-backdrop" onClick={onClose} />}
      <aside
        ref={panelRef}
        className={"sidebar" + (open ? " open" : "") + (drawer ? " drawer" : "")}
        style={{ width: open ? width : 0, "--sidebar-w": `${width}px` } as CSSProperties}
      >
        <div className="sidebar-inner">
          <div className="side-head">
            <span className="side-brand">AXIOM</span>
            
          </div>

          <div className="side-section-tabs" role="tablist" aria-label={t("ui.sidebar.sections_aria")}>
            <button
              role="tab"
              aria-selected={section === "work"}
              className={section === "work" ? "active" : ""}
              onClick={() => pickSection("work")}
            >
              <ListChecks size={13} strokeWidth={1.8} />
              <span>{t("ui.sidebar.section.work")}</span>
            </button>
            <button
              role="tab"
              aria-selected={section === "chats"}
              className={section === "chats" ? "active" : ""}
              onClick={() => pickSection("chats")}
            >
              <MessageSquarePlus size={13} strokeWidth={1.8} />
              <span>{t("ui.sidebar.section.chats")}</span>
            </button>
          </div>

          {section === "work" ? (
            <nav className="work-nav" aria-label={t("ui.project.title")}>
              <div className="side-subhead">
                <FolderOpen size={12} strokeWidth={1.8} />
                <span>{t("ui.project.title")}</span>
                <button
                  className="icon-btn tiny"
                  title={t("ui.project.open")}
                  aria-label={t("ui.project.open")}
                  onClick={onOpenWorkspaceDialog}
                >
                  <Pencil size={11} strokeWidth={2} />
                </button>
              </div>
              <div className="ws-nav-item active">
                <span className="ws-dot">{workspace?.current ? "◆" : "●"}</span>
                <span className="ws-nav-text">
                  <span className="ws-nav-name">{workspace?.current?.name ?? t("ui.chattabs.global")}</span>
                  <span className="ws-nav-path">{workspace?.current?.path ?? t("ui.project.no_folder")}</span>
                </span>
              </div>
              {(workspace?.pinned ?? []).filter((p) => p.path !== workspace?.current?.path).map((p) => (
                <button key={p.path} className="ws-nav-item" onClick={() => onSwitchWorkspace(p.path)} title={p.path}>
                  <span className="ws-dot">◆</span>
                  <span className="ws-nav-text">
                    <span className="ws-nav-name">{p.name}</span>
                    <span className="ws-nav-path">{p.path}</span>
                  </span>
                </button>
              ))}
              {(workspace?.recent ?? []).filter((r) => r.path !== workspace?.current?.path && !workspace?.pinned.some((p) => p.path === r.path)).slice(0, 4).map((p) => (
                <button key={p.path} className="ws-nav-item" onClick={() => onSwitchWorkspace(p.path)} title={p.path}>
                  <span className="ws-dot">○</span>
                  <span className="ws-nav-text">
                    <span className="ws-nav-name">{p.name}</span>
                    <span className="ws-nav-path">{p.path}</span>
                  </span>
                </button>
              ))}
              {workspace?.current && (
                <button className="ws-nav-item" onClick={onClearWorkspace} title={t("ui.project.global_hint")}>
                  <span className="ws-dot">○</span>
                  <span className="ws-nav-text">
                    <span className="ws-nav-name">{t("ui.chattabs.global")}</span>
                  </span>
                </button>
              )}

              <div className="side-subhead">
                <ListChecks size={12} strokeWidth={1.8} />
                <span>{t("ui.tabs.tasks")}</span>
                {tasks.length > 0 && <span className="ws-nav-count">{tasks.length}</span>}
                <button
                  className="icon-btn tiny"
                  title={t("ui.task.panel")}
                  aria-label={t("ui.task.panel")}
                  onClick={onOpenTaskPanel}
                >
                  <Pencil size={11} strokeWidth={2} />
                </button>
              </div>
              <div className="ws-task-list">
                {tasks.length === 0 && <div className="chat-list-empty">{t("ui.task.none")}</div>}
                {tasks.map((task) => (
                  <button
                    key={task.id}
                    className={"ws-task-item" + (task.id === focusedTaskId ? " active" : "")}
                    onClick={() => onInspectTask(task.id)}
                    title={task.goal}
                  >
                    <span className={"ws-task-state " + (task.review_recovery ? "warning" : STATE_CONFIG[task.state].tone)} />
                    <span className="ws-task-goal">{task.goal}</span>
                    {["analyzing", "planning", "executing", "verifying", "waiting_for_permission"].includes(task.state) && (
                      <Loader2 size={10} className="spin" />
                    )}
                  </button>
                ))}
              </div>
            </nav>
          ) : (
          <button className="new-chat" onClick={onNewChat} title={t("ui.sidebar.new_chat_title")}>
            <MessageSquarePlus size={16} strokeWidth={1.8} />
            <span>{t("ui.sidebar.new_chat")}</span>
            <kbd>Ctrl+N</kbd>
          </button>
          )}

          {section === "chats" && (
          <div className="side-search">
            <Search size={14} strokeWidth={1.8} />
            <input
              id="chat-search"
              placeholder={t("ui.sidebar.search_history")}
              value={search}
              onChange={(event) => onSearch(event.target.value)}
              spellCheck={false}
            />
            {search && (
              <button className="icon-btn tiny" onClick={() => onSearch("")} title={t("ui.sidebar.clear_search")}>
                <X size={12} strokeWidth={2} />
              </button>
            )}
          </div>
          )}

          {section === "chats" && (
          <nav className="chat-list">
            {groups.length === 0 && (
              <div className="chat-list-empty">
                {search ? t("ui.common.nothing_found") : t("ui.sidebar.empty")}
              </div>
            )}
            {groups.map((group) => (
              <div key={group.key} className="chat-group">
                <div className="chat-group-label">{t(`ui.sidebar.group.${group.key}`)}</div>
                {group.items.map((chat) => (
                  <div
                    key={chat.id}
                    className={"chat-item" + (chat.id === activeChatId ? " active" : "")}
                    onClick={() => (renaming === chat.id ? undefined : onOpenChat(chat.id))}
                    title={chat.model ? `${chat.title}\n${t("ui.sidebar.model_hint", { model: chat.model })}` : chat.title}
                  >
                    {renaming === chat.id ? (
                      <input
                        className="chat-rename"
                        value={draftTitle}
                        autoFocus
                        onChange={(event) => setDraftTitle(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") commitRename(chat.id);
                          if (event.key === "Escape") setRenaming(null);
                        }}
                        onBlur={() => setRenaming(null)}
                        onClick={(event) => event.stopPropagation()}
                      />
                    ) : (
                      <span className="chat-item-title">{chat.title}</span>
                    )}

                    <span className="chat-item-actions">
                      {confirmDelete === chat.id ? (
                        <>
                          <button
                            className="mini-btn danger"
                            onClick={(event) => {
                              event.stopPropagation();
                              onDeleteChat(chat.id);
                              setConfirmDelete(null);
                            }}
                          >
                            {t("ui.common.delete")}
                          </button>
                          <button
                            className="mini-btn"
                            onClick={(event) => {
                              event.stopPropagation();
                              setConfirmDelete(null);
                            }}
                          >
                            {t("ui.common.no")}
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="chat-item-btn"
                            title={t("ui.common.rename")}
                            onClick={(event) => {
                              event.stopPropagation();
                              setDraftTitle(chat.title);
                              setRenaming(chat.id);
                            }}
                          >
                            <Pencil size={12} strokeWidth={1.8} />
                          </button>
                          <button
                            className="chat-item-btn"
                            title={t("ui.sidebar.delete_chat")}
                            onClick={(event) => {
                              event.stopPropagation();
                              setConfirmDelete(chat.id);
                            }}
                          >
                            <Trash2 size={12} strokeWidth={1.8} />
                          </button>
                        </>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </nav>
          )}

          <div className="side-footer">
            <button className="side-action" onClick={onOpenModels} title={t("ui.sidebar.models_ollama")}>
              <Cpu size={15} strokeWidth={1.8} />
              <span className="side-action-label">{activeModel?.displayName ?? t("ui.common.models")}</span>
              {activeModel && <Check size={13} strokeWidth={2.2} className="side-action-ok" />}
            </button>
            <button className="side-action" onClick={onOpenSettings} title={t("ui.sidebar.settings_title")}>
              <Settings2 size={15} strokeWidth={1.8} />
              <span className="side-action-label">{t("ui.common.settings")}</span>
              <kbd>Ctrl+,</kbd>
            </button>
            <div className="side-meta">
              {totalChats === 0 ? (
                <>
                  <Clock size={12} strokeWidth={1.8} />
                  <span>{t("ui.sidebar.history_empty")}</span>
                </>
              ) : confirmDeleteAll ? (
                <>
                  <button
                    className="mini-btn danger"
                    onClick={() => {
                      setConfirmDeleteAll(false);
                      void onDeleteAllChats();
                    }}
                  >
                    {t("ui.sidebar.delete_all", { n: String(totalChats) })}
                  </button>
                  <button className="mini-btn" onClick={() => setConfirmDeleteAll(false)}>
                    {t("ui.common.no")}
                  </button>
                </>
              ) : (
                <>
                  <Clock size={12} strokeWidth={1.8} />
                  <span>
                    {plural("ui.sidebar.conversation", totalChats, locale, strings)}
                  </span>
                  <button
                    className="icon-btn tiny"
                    title={t("ui.sidebar.clear_all")}
                    onClick={() => setConfirmDeleteAll(true)}
                  >
                    <Trash2 size={12} strokeWidth={1.8} />
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
        {!drawer && <div className="sidebar-resizer" onMouseDown={startDrag} />}
      </aside>
    </>
  );
}