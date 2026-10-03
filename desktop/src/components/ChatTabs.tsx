/**
 * W3.3: chat tab strip — project/model/context-isolated conversations.
 *
 * A tab is a descriptor; the real workspace/model/conversation switches are
 * performed by the core `ChatSession` through `tab_activate` (no parallel
 * runtime). Background tasks keep running regardless of the active tab.
 */
import { useEffect, useRef } from "react";
import { Globe, Loader2, Plus, X } from "lucide-react";
import type { ChatTab } from "../types";
import { useLocale } from "../lib/locale";
import { plural } from "../lib/i18n";

interface Props {
  tabs: ChatTab[];
  onOpen: () => void;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
  /** W3.3: background task count shown next to the active tab label. */
  runningTasks: number;
  /** W3.3: collections being indexed in the background. */
  indexing: string[];
}

const TRUNCATE = 26;

/** Close button title/aria: "Close tab {title}". */
function closeLabel(t: (key: string, vars?: Record<string, string>) => string, title: string) {
  return t("ui.chattabs.close_aria", { title: title.slice(0, TRUNCATE) });
}

export default function ChatTabs({ tabs, onOpen, onActivate, onClose, runningTasks, indexing }: Props) {
  const { t, locale } = useLocale();
  const stripRef = useRef<HTMLDivElement>(null);
  // Keyboard navigation on the strip: Ctrl+Tab / Ctrl+Shift+Tab cycle tabs.
  useEffect(() => {
    const strip = stripRef.current;
    if (!strip) return;
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key !== "Tab") return;
      const active = tabs.find((tab) => tab.active);
      if (!active) return;
      const index = tabs.findIndex((tab) => tab.id === active.id);
      const next = tabs[(index + (event.shiftKey ? -1 : 1) + tabs.length) % tabs.length];
      if (next) {
        event.preventDefault();
        onActivate(next.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tabs, onActivate]);

  // The strip scrolls to keep the active tab visible after workspace switches.
  useEffect(() => {
    stripRef.current
      ?.querySelector<HTMLElement>(".chattab.active")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tabs]);

  const runningLabel =
    runningTasks > 0 ? plural("ui.chattabs.running", runningTasks, locale) : null;

  return (
    <div className="chattabs" role="tablist" aria-label={t("ui.chattabs.aria")}>
      <div className="chattabs-strip" ref={stripRef}>
        {tabs.map((tab) => {
          const title =
            tab.workspace
              ? tab.title
              : tab.title || t("ui.chattabs.global");
          const short = title.length > TRUNCATE ? `${title.slice(0, TRUNCATE - 1)}…` : title;
          const busy = tab.active && (runningTasks > 0 || indexing.length > 0);
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`chattab-${tab.id}`}
              aria-selected={tab.active}
              tabIndex={tab.active ? 0 : -1}
              className={"chattab" + (tab.active ? " active" : "")}
              title={
                (tab.workspace ?? t("ui.chattabs.global")) +
                (tab.model ? `\n${t("ui.sidebar.model_hint", { model: tab.model })}` : "")
              }
              onClick={() => onActivate(tab.id)}
            >
              {!tab.workspace && <Globe size={11} strokeWidth={1.8} />}
              <span className="chattab-title">{short}</span>
              {busy && <Loader2 size={10} className="spin" />}
              <span
                className="chattab-close"
                role="button"
                tabIndex={-1}
                title={closeLabel(t, title)}
                aria-label={closeLabel(t, title)}
                onClick={(event) => {
                  event.stopPropagation();
                  onClose(tab.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    event.stopPropagation();
                    onClose(tab.id);
                  }
                }}
              >
                <X size={11} strokeWidth={2} />
              </span>
            </button>
          );
        })}
      </div>
      {runningLabel && <span className="chattabs-running">{runningLabel}</span>}
      <button
        type="button"
        className="chattabs-new"
        onClick={onOpen}
        title={t("ui.chattabs.new_title")}
        aria-label={t("ui.chattabs.new_title")}
      >
        <Plus size={12} strokeWidth={2} />
      </button>
    </div>
  );
}
