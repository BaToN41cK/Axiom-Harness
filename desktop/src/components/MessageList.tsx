import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import {
  ChevronDown,
  ChevronUp,
  Cpu,
  ExternalLink,
  Globe,
  Pencil,
  Play,
  Quote,
  Search,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import type { AxiomConfig, LiveMessage } from "../types";
import { Favicon, MessageError, SourcesList, hostOf, pathOf } from "./ToolBits";
import { ToolActivityTimeline } from "./ToolActivity";
import OrchestrationBoard from "./OrchestrationBoard";
import CodeBlock, { CopyIconButton } from "./CodeBlock";
import ArtifactView from "./ArtifactView";
import { formatElapsed } from "../lib/format";
import { useLocale } from "../lib/locale";

interface Props {
  messages: LiveMessage[];
  generating: boolean;
  statusText: string | null;
  liveState: string;
  elapsedMs: number;
  config: AxiomConfig | null;
  modelName: string | null;
  modelCapabilities: string[];
  /** Global Chat mode: no project folder is active. */
  globalChat?: boolean;
  onEdit: (text: string) => void;
  onQuote: (text: string) => void;
  onOpen: (url: string) => void;
  onSuggestion: (text: string, forceSearch?: boolean) => void;
  onStop: () => void;
  onContinue: () => void;
}

const SUGGESTIONS: { key: string; search?: boolean }[] = [
  { key: "ui.chat.suggestion.1" },
  { key: "ui.chat.suggestion.2" },
  { key: "ui.chat.suggestion.3" },
  { key: "ui.chat.suggestion.4", search: true },
];

/** Human wording of the live backend state (never invented). */
function liveStateKey(state: string): string {
  switch (state) {
    case "connecting": return "ui.live.connecting";
    case "loading": return "ui.live.loading";
    case "thinking": return "ui.live.thinking";
    case "tool_call": return "ui.live.tool_call";
    case "searching": return "ui.live.searching";
    case "receiving": return "ui.live.receiving";
    case "cancelled": return "ui.live.cancelled";
    case "error": return "ui.live.error";
    case "ready": return "ui.live.ready";
    default: return "ui.live.receiving";
  }
}

export default function MessageList(props: Props) {
  const {
    messages,
    generating,
    statusText,
    liveState,
    elapsedMs,
    config,
    modelName,
    modelCapabilities,
    globalChat = false,
    onEdit,
    onQuote,
    onOpen,
    onSuggestion,
    onStop,
    onContinue,
  } = props;
  const { t } = useLocale();

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  // W3.9 in-conversation Ctrl+F: search only the mounted transcript of the
  // current chat. Matches are message ids (content + thinking, case-insensitive);
  // navigation scrolls the real message element into view.
  const [findOpen, setFindOpen] = useState(false);
  const [findQuery, setFindQuery] = useState("");
  const [findIndex, setFindIndex] = useState(0);
  const findInputRef = useRef<HTMLInputElement>(null);

  const findMatches = useMemo(() => {
    const needle = findQuery.trim().toLowerCase();
    if (!needle) return [] as string[];
    return messages
      .filter((message) => {
        const haystack = `${message.content} ${message.thinking ?? ""}`.toLowerCase();
        return needle.length > 0 && haystack.includes(needle);
      })
      .map((message) => message.id);
  }, [messages, findQuery]);

  const openFind = useCallback(() => {
    setFindOpen(true);
    setFindIndex(0);
    window.setTimeout(() => findInputRef.current?.focus(), 60);
  }, []);

  const closeFind = useCallback(() => {
    setFindOpen(false);
    setFindQuery("");
    setFindIndex(0);
  }, []);

  // Reset the cursor when another conversation replaces the transcript or the
  // query set shrinks underneath it.
  useEffect(() => {
    setFindIndex(0);
  }, [messages]);
  useEffect(() => {
    setFindIndex((index) => (findMatches.length ? index % findMatches.length : 0));
  }, [findMatches]);

  const gotoMatch = useCallback(
    (direction: 1 | -1) => {
      if (findMatches.length === 0) return;
      setFindIndex((index) => {
        const next = (index + direction + findMatches.length) % findMatches.length;
        const targetId = findMatches[next];
        window.setTimeout(() => {
          document
            .querySelector(`[data-message-id="${CSS.escape(targetId)}"]`)
            ?.scrollIntoView({ block: "center", behavior: "smooth" });
        }, 30);
        return next;
      });
    },
    [findMatches],
  );

  // The global Ctrl+F handler lives in the store hook; a custom event keeps the
  // bar next to the transcript it searches (TUI keeps the same separation).
  useEffect(() => {
    const open = () => openFind();
    window.addEventListener("axiom-find-chat", open);
    return () => window.removeEventListener("axiom-find-chat", open);
  }, [openFind]);

  // Stable callback identities so memoised rows never re-render just because a
  // parent render produced fresh function objects. The refs always point at the
  // latest store callbacks, so behavior is identical — no stale closures.
  const cbRef = useRef({ onEdit, onQuote, onOpen, onStop, onContinue });
  cbRef.current = { onEdit, onQuote, onOpen, onStop, onContinue };
  const stable = useMemo(
    () => ({
      onEdit: (text: string) => cbRef.current.onEdit(text),
      onQuote: (text: string) => cbRef.current.onQuote(text),
      onOpen: (url: string) => cbRef.current.onOpen(url),
      onStop: () => cbRef.current.onStop(),
      onContinue: () => cbRef.current.onContinue(),
    }),
    [],
  );

  const lastUserId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") return messages[i].id;
    }
    return null;
  }, [messages]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
  };

  const findBar = findOpen && (
    <div className="chat-find" role="search">
      <Search size={13} strokeWidth={1.8} />
      <input
        ref={findInputRef}
        id="chat-find-input"
        placeholder={t("ui.chat.find_placeholder")}
        value={findQuery}
        onChange={(event) => {
          setFindQuery(event.target.value);
          setFindIndex(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            gotoMatch(event.shiftKey ? -1 : 1);
          }
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            closeFind();
          }
        }}
        spellCheck={false}
      />
      <span className="chat-find-count" aria-live="polite">
        {findQuery.trim()
          ? findMatches.length > 0
            ? `${findIndex + 1}/${findMatches.length}`
            : t("ui.chat.no_matches")
          : ""}
      </span>
      <button
        className="icon-btn tiny"
        title={t("ui.chat.find_prev")}
        onClick={() => gotoMatch(-1)}
        disabled={findMatches.length === 0}
      >
        <ChevronUp size={13} strokeWidth={1.8} />
      </button>
      <button
        className="icon-btn tiny"
        title={t("ui.chat.find_next")}
        onClick={() => gotoMatch(1)}
        disabled={findMatches.length === 0}
      >
        <ChevronDown size={13} strokeWidth={1.8} />
      </button>
      <button className="icon-btn tiny" onClick={closeFind} title={t("ui.chat.close_find")}>
        <X size={13} strokeWidth={1.8} />
      </button>
    </div>
  );

  useEffect(() => {
    if (!config?.auto_scroll) return;
    if (!stickRef.current) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, config?.auto_scroll]);

  if (messages.length === 0) {
    return (
      <div className="chat-scroll">
        {findBar}
        <div className="chat-inner welcome-wrap">
          <div className="welcome">
            <div className="welcome-mark">
              <Sparkles size={30} strokeWidth={1.4} />
            </div>
            <h1 className="welcome-title">AXIOM</h1>
            <p className="welcome-sub">{t("ui.chat.welcome")}</p>
            <div className="welcome-model">
              <Cpu size={13} strokeWidth={1.8} />
              <span>{modelName ?? t("ui.topbar.no_model")}</span>
              {modelCapabilities.length > 0 && (
                <span className="welcome-caps">{modelCapabilities.join(" · ")}</span>
              )}
            </div>
            {globalChat && (
              <div className="welcome-global" title={t("ui.chat.global_title")}>
                <Globe size={12} strokeWidth={1.8} />
                <span>{t("ui.chat.global_note")}</span>
              </div>
            )}
            <div className="welcome-suggestions">
              {SUGGESTIONS.map((item, index) => (
                <button
                  key={item.key}
                  className="suggestion"
                  style={{ animationDelay: `${0.08 * index + 0.1}s` }}
                  onClick={() => onSuggestion(t(item.key), item.search)}
                  title={item.search ? t("ui.chat.suggest_search") : t("ui.chat.suggest_send")}
                >
                  {item.search && <Sparkles size={12} strokeWidth={1.8} />}
                  {t(item.key)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      {findBar}
      <div className="chat-inner">
        {messages.map((message) =>
          message.role === "user" ? (
            <UserMessage
              key={message.id}
              message={message}
              editable={message.id === lastUserId && !generating}
              onEdit={stable.onEdit}
              onQuote={stable.onQuote}
              findActive={findOpen && findQuery.trim() !== "" && findMatches.includes(message.id)}
            />
          ) : (
            <AssistantMessage
              key={message.id}
              message={message}
              config={config}
              generating={generating}
              liveState={message.streaming ? liveState : ""}
              statusText={message.streaming ? statusText : null}
              elapsedMs={message.streaming ? elapsedMs : 0}
              onOpen={stable.onOpen}
              onQuote={stable.onQuote}
              onStop={stable.onStop}
              onContinue={stable.onContinue}
              findActive={findOpen && findQuery.trim() !== "" && findMatches.includes(message.id)}
            />
          ),
        )}
      </div>
    </div>
  );
}

const UserMessage = memo(function UserMessage({
  message,
  editable,
  onEdit,
  onQuote,
  findActive,
}: {
  message: LiveMessage;
  editable: boolean;
  onEdit: (text: string) => void;
  onQuote: (text: string) => void;
  findActive?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const { t } = useLocale();

  useEffect(() => {
    if (!editing) return;
    const area = areaRef.current;
    if (!area) return;
    area.focus();
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
  }, [editing]);

  return (
    <div className={"msg user" + (editing ? " editing" : "") + (findActive ? " find-hit" : "")} data-message-id={message.id}>
      {!editing && (
        <div className="msg-head">
          <span className="msg-role">YOU</span>
          {editable && (
            <div className="msg-tools">
              <button
                className="msg-action"
                title={t("ui.chat.edit_title")}
                onClick={() => {
                  setDraft(message.content);
                  setEditing(true);
                }}
              >
                <Pencil size={13} strokeWidth={1.9} />
                <span>{t("ui.chat.edit")}</span>
              </button>
              <QuoteAction text={message.content} onQuote={onQuote} label={t("ui.chat.quote_prompt")} />
            </div>
          )}
        </div>
      )}

      {message.images && message.images.length > 0 && (
        <div className="msg-images">
          {message.images.map((image, index) => (
            <img key={index} src={image} alt={t("ui.composer.attachment", { n: String(index + 1) })} />
          ))}
        </div>
      )}

      {editing ? (
        <div className="edit-box">
          <div className="edit-label">
            <Pencil size={12} strokeWidth={2} />
            <span>{t("ui.chat.editing")}</span>
            <span className="edit-label-note">{t("ui.chat.editing_note")}</span>
          </div>
          <textarea
            ref={areaRef}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              const area = event.target;
              area.style.height = "auto";
              area.style.height = `${area.scrollHeight}px`;
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                setEditing(false);
              }
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                if (draft.trim()) {
                  setEditing(false);
                  onEdit(draft);
                }
              }
            }}
            spellCheck={false}
          />
          <div className="edit-actions">
            <span className="edit-hint">
              {t("ui.chat.edit_hint")}
            </span>
            <div className="edit-actions-btns">
              <button className="btn ghost small" onClick={() => setEditing(false)}>
                {t("ui.common.cancel")}
              </button>
              <button
                className="btn primary small"
                disabled={!draft.trim()}
                onClick={() => {
                  setEditing(false);
                  onEdit(draft);
                }}
              >
                {t("ui.chat.resend")}
              </button>
            </div>
          </div>
        </div>
      ) : (
        message.content && <div className="msg-user-bubble">{message.content}</div>
      )}
    </div>
  );
});

const AssistantMessage = memo(function AssistantMessage({
  message,
  config,
  generating,
  liveState,
  statusText,
  elapsedMs,
  onOpen,
  onQuote,
  onStop,
  onContinue,
  findActive,
}: {
  message: LiveMessage;
  config: AxiomConfig | null;
  generating: boolean;
  liveState: string;
  statusText: string | null;
  elapsedMs: number;
  onOpen: (url: string) => void;
  onQuote: (text: string) => void;
  onStop: () => void;
  onContinue: () => void;
  findActive?: boolean;
}) {
  const streaming = message.streaming;
  const cancelled = message.metrics?.state === "cancelled";
  const failed = message.metrics?.state === "error" || !!message.error;
  const { t } = useLocale();

  return (
    <div className={"msg assistant" + (findActive ? " find-hit" : "")} data-message-id={message.id}>
      <div className="msg-head">
        <span className="msg-role">AXIOM</span>
        {streaming && (
          <span className="live-pill">
            <span className="live-dot" />
            <span>{statusText ?? t(liveStateKey(liveState))}</span>
            <span className="live-sep" />
            <span className="live-time">{formatElapsed(elapsedMs)}</span>
            {generating && (
              <button className="stop-inline" onClick={onStop} title={t("ui.chat.stop_title")}>
                <Square size={10} strokeWidth={2.2} fill="currentColor" />
              </button>
            )}
          </span>
        )}
        {message.content && !streaming && (
          <div className="msg-tools">
            <CopyIconButton text={message.content} title={t("ui.chat.copy_answer")} />
            <QuoteAction text={message.content} onQuote={onQuote} label={t("ui.chat.quote_prompt")} />
          </div>
        )}
      </div>

      <ThinkingSection
        thinking={message.thinking}
        streaming={streaming}
        visible={config?.show_reasoning ?? true}
        expandedByDefault={config?.reasoning_expanded ?? false}
      />

      {message.orchestration ? (
        <OrchestrationBoard
          state={message.orchestration}
          live={streaming}
          elapsedMs={elapsedMs}
        />
      ) : (
        <>
          <ToolActivityTimeline calls={message.toolCalls} />

          {message.sources.length > 0 && <SourcesList sources={message.sources} onOpen={onOpen} />}
        </>
      )}

      {message.content &&
        !message.orchestration &&
        (streaming ? (
          // While tokens arrive: plain incremental text (no markdown re-parse -> no flicker).
          <div className="stream-view">
            {message.content}
            <span className="caret" />
          </div>
        ) : config?.render_markdown ?? true ? (
          <div className="markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw, rehypeSanitize]}
              components={{
                code: MarkdownCode,
                a: ({ href, children }) => (
                  <MarkdownLink href={href} onOpen={onOpen}>
                    {children}
                  </MarkdownLink>
                ),
                details: ({ children }) => <details className="md-details">{children}</details>,
                summary: ({ children }) => <summary className="md-summary">{children}</summary>,
                table: ({ children }) => (
                  <div className="table-wrap">
                    <table>{children}</table>
                  </div>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
            {streaming && <span className="caret" />}
          </div>
        ) : (
          <div className={"markdown plain" + (streaming ? " streaming" : "")}>
            {message.content}
            {streaming && <span className="caret" />}
          </div>
        ))}

      {message.artifacts && message.artifacts.length > 0 && (
        <div className="artifact-list">
          {message.artifacts.map((artifact, index) => (
            <ArtifactView key={index} artifact={artifact} />
          ))}
        </div>
      )}

      {!streaming && cancelled && (
        <div className="msg-note cancelled-resume">
          {message.content ? (
            <button
              className="resume-btn"
              onClick={onContinue}
              disabled={generating}
              title={t("ui.chat.continue_title")}
            >
              <Play size={12} strokeWidth={2} fill="currentColor" />
              <span>{t("ui.chat.continue")}</span>
            </button>
          ) : (
            <>
              <Square size={12} strokeWidth={2} />
              <span>{t("ui.chat.stopped")}</span>
            </>
          )}
        </div>
      )}

      {message.error && <MessageError message={message.error.message} hint={message.error.hint} />}

      {!streaming && failed && message.metrics?.stopReason && (
        <div className="msg-note stop-reason">
          <Square size={12} strokeWidth={2} />
          <span>
            {message.metrics.stopReason === "tool_round_limit"
              ? t("ui.chat.tool_round_limit")
              : t("ui.chat.gen_error")}
          </span>
        </div>
      )}
      {!streaming && !failed && (config?.show_metrics ?? true) && message.metrics && (
        <div className="msg-metrics">
          {message.metrics.tokensOut != null && <span>{message.metrics.tokensOut} tok out</span>}
          {message.metrics.tokensIn != null && <span>{message.metrics.tokensIn} tok in</span>}
          {message.metrics.tokensPerSecond != null && (
            <span>{message.metrics.tokensPerSecond.toFixed(1)} tok/s</span>
          )}
          {message.metrics.ttftMs != null && (
            <span>TTFT {(message.metrics.ttftMs / 1000).toFixed(1)}s</span>
          )}
          {message.metrics.loadMs != null && message.metrics.loadMs > 0 && (
            <span>{t("ui.chat.load", { n: (message.metrics.loadMs / 1000).toFixed(1) })}</span>
          )}
          {message.metrics.durationMs > 0 && <span>{formatElapsed(message.metrics.durationMs)}</span>}
        </div>
      )}
    </div>
  );
});

/** W3.9 quote-to-prompt: the current text selection inside this message is
 *  appended to the composer draft as a `> ` blockquote and focused. Empty
 *  selections fall back to quoting the whole message — never to an empty quote. */
function QuoteAction({
  text,
  onQuote,
  label,
}: {
  text: string;
  onQuote: (text: string) => void;
  label: string;
}) {
  const { t } = useLocale();
  return (
    <button
      className="msg-action"
      title={label}
      onClick={() => {
        const raw = window.getSelection()?.toString().trim() || text.trim();
        if (!raw) return;
        onQuote(raw);
      }}
    >
      <Quote size={13} strokeWidth={1.9} />
      <span>{t("ui.chat.quote")}</span>
    </button>
  );
}

/** Markdown `code` renderer: fenced blocks get the AXIOM code card. */
function MarkdownCode(props: { className?: string; children?: ReactNode }) {
  const { className, children } = props;
  const language = /language-([\w+#-]+)/.exec(className ?? "")?.[1];
  const text = Array.isArray(children) ? children.join("") : String(children ?? "");
  const trimmed = text.replace(/\n$/, "");
  if (!language && !trimmed.includes("\n")) {
    return <code className="md-inline">{children}</code>;
  }
  return <CodeBlock code={trimmed} language={language} />;
}

/** Pretty markdown link: dotted underline, hover preview card, click opens externally. */
function MarkdownLink({
  href,
  children,
  onOpen,
}: {
  href?: string;
  children?: ReactNode;
  onOpen: (url: string) => void;
}) {
  const [preview, setPreview] = useState(false);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    };
  }, []);

  if (!href) return <>{children}</>;

  const label =
    typeof children === "string"
      ? children
      : Array.isArray(children)
        ? children.filter((child): child is string => typeof child === "string").join("")
        : "";
  const host = hostOf(href);

  const armShow = () => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setPreview(true), 350);
  };
  const armHide = () => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    setPreview(false);
  };

  return (
    <a
      className="md-link"
      href={href}
      title={href}
      onMouseEnter={armShow}
      onMouseLeave={armHide}
      onClick={(event) => {
        event.preventDefault();
        armHide();
        onOpen(href);
      }}
    >
      {children}
      {preview && host && (
        <span className="link-card">
          <Favicon url={href} size={16} />
          <span className="link-card-body">
            <span className="link-card-title">{label || href}</span>
            <span className="link-card-url">
              <b>{host}</b>
              {pathOf(href)}
            </span>
          </span>
          <ExternalLink size={12} strokeWidth={1.8} className="link-card-icon" />
        </span>
      )}
    </a>
  );
}

/** Real reasoning only: hidden when the model sends none, collapsible always. */
function ThinkingSection({
  thinking,
  streaming,
  visible,
  expandedByDefault,
}: {
  thinking: string;
  streaming: boolean;
  visible: boolean;
  expandedByDefault: boolean;
}) {
  const active = streaming && thinking.length > 0;
  const [open, setOpen] = useState(expandedByDefault);
  const bodyRef = useRef<HTMLDivElement>(null);
  const { t } = useLocale();

  // While reasoning streams in, the trace is force-expanded so the user
  // sees the model's actual thoughts live; afterwards respect the setting.
  useEffect(() => {
    setOpen(active ? true : expandedByDefault);
  }, [active, expandedByDefault]);

  // Keep the tail of the reasoning text in view while it grows.
  useEffect(() => {
    if (active && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [thinking, active]);

  if (!visible || !thinking) return null;
  const shown = open || active;

  return (
    <div className={"think" + (active ? " live" : "")}>
      <button
        className="think-head"
        onClick={() => setOpen((v) => !v)}
        title={open ? t("ui.chat.think_collapse") : t("ui.chat.think_show")}
      >
        <span className="think-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="think-title">{active ? t("ui.chat.thinking") : t("ui.chat.thinking_process")}</span>
        <ChevronDown size={13} strokeWidth={1.8} className={"think-chev" + (open ? " open" : "")} />
      </button>
      <div className={"think-wrap" + (shown ? " open" : "")}>
        <div ref={bodyRef} className="think-text">
          {thinking}
        </div>
      </div>
    </div>
  );
}