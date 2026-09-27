import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, FolderOpen, Globe, MessageSquare, Pin, X } from "lucide-react";
import type { ProjectInfo } from "../types";
import Presence from "./Presence";
import { playUiSound } from "../lib/sound";

interface Props {
  current: ProjectInfo | null;
  recent: ProjectInfo[];
  pinned: ProjectInfo[];
  onOpen: () => void;
  onSwitch: (path: string) => void;
  onClear: () => void;
  onRemove: (path: string) => void;
  onTogglePin: (path: string) => void;
}

/**
 * Project/workspace selector in the top bar (§3).
 * Reuses the existing backend (set_workspace / clear_workspace / pin) —
 * the "Global Chat" entry is the real `clear_workspace` bridge command and
 * switches immediately (no confirmation — the user can always switch back).
 * Removing a project from the list (✕) asks for confirmation: the dialog makes
 * clear that only the list entry is dropped, never the project on disk.
 */
export default function ProjectSelector(props: Props) {
  const { current, recent, pinned, onOpen, onSwitch, onClear, onRemove, onTogglePin } = props;
  const [open, setOpen] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);
  const others = recent.filter((r) => r.path !== current?.path);
  const currentPinned = pinned.some((p) => p.path === current?.path);
  return (
    <div className="ws-selector" ref={ref}>
      <button
        className={"ws-current" + (current ? "" : " none")}
        onClick={() => { playUiSound("panel"); setOpen((v) => !v); }}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={current?.path ?? "Глобальный чат — проект не открыт"}
      >
        {current ? (
          <FolderOpen size={14} strokeWidth={1.8} />
        ) : (
          <Globe size={14} strokeWidth={1.8} />
        )}
        <span className="ws-name" key={current?.path ?? "global"}>{current?.name ?? "Global Chat"}</span>
        {current && <span className="ws-kind">{current.kind}</span>}
        <ChevronDown size={13} strokeWidth={1.8} className={"chevron" + (open ? " open" : "")} />
      </button>
      <Presence open={open}>
        <div className="ws-menu" role="listbox">
          <div className="ws-menu-title">Проекты</div>
          {current && (
            <div className="ws-item active">
              <span className="ws-dot">{currentPinned ? "◆" : "●"}</span>
              <span className="ws-item-text">
                <span className="ws-item-name">{current.name}</span>
                <span className="ws-item-path">{current.path}</span>
              </span>
              <button
                className="icon-btn tiny"
                title={currentPinned ? "Открепить проект" : "Прикрепить проект"}
                onClick={() => void onTogglePin(current.path)}
              >
                <Pin size={12} strokeWidth={1.8} fill={currentPinned ? "currentColor" : "none"} />
              </button>
              <button
                className="icon-btn tiny ws-leave"
                title="Удалить проект из списка"
                onClick={() => setConfirmRemove(current.path)}
              >
                <X size={12} strokeWidth={1.8} />
              </button>
            </div>
          )}
          {pinned.filter((p) => p.path !== current?.path).length > 0 && (
            <div className="ws-subtitle">Прикрепленные</div>
          )}
          {pinned
            .filter((p) => p.path !== current?.path)
            .map((p) => (
              <div key={p.path} className="ws-item">
                <button
                  className="ws-item-main"
                  onClick={() => {
                    setOpen(false);
                    void onSwitch(p.path);
                  }}
                >
                  <span className="ws-dot">◆</span>
                  <span className="ws-item-text">
                    <span className="ws-item-name">{p.name}</span>
                    <span className="ws-item-path">{p.path}</span>
                  </span>
                </button>
                <button className="icon-btn tiny" title="Открепить проект" onClick={() => void onTogglePin(p.path)}>
                  <Pin size={12} strokeWidth={1.8} fill="currentColor" />
                </button>
              </div>
            ))}
          {others.length > 0 && <div className="ws-subtitle">Недавние</div>}
          {others.map((p) => (
            <div key={p.path} className="ws-item">
              <button
                className="ws-item-main"
                onClick={() => {
                  setOpen(false);
                  void onSwitch(p.path);
                }}
              >
                <span className="ws-dot">○</span>
                <span className="ws-item-text">
                  <span className="ws-item-name">{p.name}</span>
                  <span className="ws-item-path">{p.path}</span>
                </span>
              </button>
              <button className="icon-btn tiny" title="Удалить из списка" onClick={() => setConfirmRemove(p.path)}>
                <X size={12} strokeWidth={1.8} />
              </button>
            </div>
          ))}
          <div className="ws-menu-sep" />
          {!current && (
            <div className="ws-item active">
              <button className="ws-item-main" disabled>
                <Check size={14} strokeWidth={2} className="ws-check" />
                <span className="ws-item-text">
                  <span className="ws-item-name">Global Chat</span>
                  <span className="ws-item-path">Без папки проекта</span>
                </span>
              </button>
            </div>
          )}
          {current && (
            <button
              className="ws-global"
              onClick={() => {
                setOpen(false);
                void onClear();
              }}
              title="Общаться без проекта: файловые инструменты отключены"
            >
              <MessageSquare size={14} strokeWidth={1.8} /> Global Chat
            </button>
          )}
          <button className="ws-open" onClick={() => { setOpen(false); void onOpen(); }}>
            <FolderOpen size={14} strokeWidth={1.8} /> Открыть проект…
          </button>
        </div>
      </Presence>

      <Presence open={!!confirmRemove}>
      {confirmRemove && (
        <div className="modal-backdrop" onClick={() => setConfirmRemove(null)}>
          <div className="modal confirm" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h2>⚠ Удалить проект из списка?</h2>
            </div>
            <div className="modal-body">
              <code className="confirm-detail">{confirmRemove}</code>
              <p className="about-text">
                Проект исчезнет из списка селектора. <b>Файлы на диске не удаляются</b>,
                а открытый проект останется активным, пока вы не переключитесь сами.
                Вернуть его в список можно кнопкой «Открыть проект…».
              </p>
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={() => setConfirmRemove(null)}>Отказаться</button>
              <div className="modal-foot-spacer" />
              <button
                className="btn danger"
                onClick={() => {
                  const target = confirmRemove;
                  setConfirmRemove(null);
                  setOpen(false);
                  if (target) void onRemove(target);
                }}
              >
                Удалить из списка
              </button>
            </div>
          </div>
        </div>
      )}
      </Presence>
    </div>
  );
}
