import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Check, Clock, Cpu, MessageSquarePlus, Pencil, Search, Settings2, Trash2, X } from "lucide-react";
import type { Conversation, ModelInfo } from "../types";

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
}

interface Group {
  label: string;
  items: Conversation[];
}

/** Real timestamps, real day buckets (today / yesterday / week / older). */
function groupChats(chats: Conversation[]): Group[] {
  const now = Date.now() / 1000;
  const dayStart = new Date().setHours(0, 0, 0, 0) / 1000;
  const groups: Record<string, Conversation[]> = {
    Сегодня: [],
    Вчера: [],
    "Последние 7 дней": [],
    Ранее: [],
  };
  for (const chat of chats) {
    const stamp = chat.updatedAt;
    if (stamp >= dayStart) groups["Сегодня"].push(chat);
    else if (stamp >= dayStart - 86400) groups["Вчера"].push(chat);
    else if (stamp >= now - 7 * 86400) groups["Последние 7 дней"].push(chat);
    else groups["Ранее"].push(chat);
  }
  return Object.entries(groups)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
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
  } = props;

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

          <button className="new-chat" onClick={onNewChat} title="Новый чат (Ctrl+N)">
            <MessageSquarePlus size={16} strokeWidth={1.8} />
            <span>Новый чат</span>
            <kbd>Ctrl+N</kbd>
          </button>

          <div className="side-search">
            <Search size={14} strokeWidth={1.8} />
            <input
              id="chat-search"
              placeholder="Поиск по истории…"
              value={search}
              onChange={(event) => onSearch(event.target.value)}
              spellCheck={false}
            />
            {search && (
              <button className="icon-btn tiny" onClick={() => onSearch("")} title="Очистить поиск">
                <X size={12} strokeWidth={2} />
              </button>
            )}
          </div>

          <nav className="chat-list">
            {groups.length === 0 && (
              <div className="chat-list-empty">
                {search ? "Ничего не найдено" : "История пуста — начните разговор"}
              </div>
            )}
            {groups.map((group) => (
              <div key={group.label} className="chat-group">
                <div className="chat-group-label">{group.label}</div>
                {group.items.map((chat) => (
                  <div
                    key={chat.id}
                    className={"chat-item" + (chat.id === activeChatId ? " active" : "")}
                    onClick={() => (renaming === chat.id ? undefined : onOpenChat(chat.id))}
                    title={chat.model ? `${chat.title}\nмодель: ${chat.model}` : chat.title}
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
                            Удалить
                          </button>
                          <button
                            className="mini-btn"
                            onClick={(event) => {
                              event.stopPropagation();
                              setConfirmDelete(null);
                            }}
                          >
                            Нет
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="chat-item-btn"
                            title="Переименовать"
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
                            title="Удалить разговор"
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

          <div className="side-footer">
            <button className="side-action" onClick={onOpenModels} title="Модели Ollama">
              <Cpu size={15} strokeWidth={1.8} />
              <span className="side-action-label">{activeModel?.displayName ?? "Модели"}</span>
              {activeModel && <Check size={13} strokeWidth={2.2} className="side-action-ok" />}
            </button>
            <button className="side-action" onClick={onOpenSettings} title="Настройки (Ctrl+,)">
              <Settings2 size={15} strokeWidth={1.8} />
              <span className="side-action-label">Настройки</span>
              <kbd>Ctrl+,</kbd>
            </button>
            <div className="side-meta">
              {totalChats === 0 ? (
                <>
                  <Clock size={12} strokeWidth={1.8} />
                  <span>История пуста</span>
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
                    Удалить все ({totalChats})
                  </button>
                  <button className="mini-btn" onClick={() => setConfirmDeleteAll(false)}>
                    Нет
                  </button>
                </>
              ) : (
                <>
                  <Clock size={12} strokeWidth={1.8} />
                  <span>
                    {totalChats} {totalChats === 1 ? "разговор" : "разговоров"}
                  </span>
                  <button
                    className="icon-btn tiny"
                    title="Очистить всю историю"
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