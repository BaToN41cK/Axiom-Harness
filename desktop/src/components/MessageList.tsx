import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import {
  ChevronDown,
  Cpu,
  ExternalLink,
  Globe,
  Pencil,
  Play,
  Sparkles,
  Square,
} from "lucide-react";
import type { AxiomConfig, LiveMessage } from "../types";
import { Favicon, MessageError, SourcesList, hostOf, pathOf } from "./ToolBits";
import { ToolActivityTimeline } from "./ToolActivity";
import OrchestrationBoard from "./OrchestrationBoard";
import CodeBlock, { CopyIconButton } from "./CodeBlock";
import { formatElapsed } from "../lib/format";

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
  onOpen: (url: string) => void;
  onSuggestion: (text: string, forceSearch?: boolean) => void;
  onStop: () => void;
  onContinue: () => void;
}

const SUGGESTIONS: { text: string; search?: boolean }[] = [
  { text: "Что ты умеешь?" },
  { text: "Напиши на Python функцию с обработкой ошибок" },
  { text: "Разбери этот код и предложи улучшения" },
  { text: "Какая сейчас последняя стабильная версия Python?", search: true },
];

/** Human wording of the live backend state (never invented). */
function liveStateLabel(state: string): string {
  switch (state) {
    case "connecting":
      return "Подключение";
    case "loading":
      return "Загружает модель";
    case "thinking":
      return "Размышляет";
    case "tool_call":
      return "Инструмент";
    case "searching":
      return "Веб-поиск";
    case "receiving":
      return "Генерация";
    case "cancelled":
      return "Остановлено";
    case "error":
      return "Ошибка";
    case "ready":
      return "Готов";
    default:
      return "Генерация";
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
    onOpen,
    onSuggestion,
    onStop,
    onContinue,
  } = props;

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  // Stable callback identities so memoised rows never re-render just because a
  // parent render produced fresh function objects. The refs always point at the
  // latest store callbacks, so behavior is identical — no stale closures.
  const cbRef = useRef({ onEdit, onOpen, onStop, onContinue });
  cbRef.current = { onEdit, onOpen, onStop, onContinue };
  const stable = useMemo(
    () => ({
      onEdit: (text: string) => cbRef.current.onEdit(text),
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
        <div className="chat-inner welcome-wrap">
          <div className="welcome">
            <div className="welcome-mark">
              <Sparkles size={30} strokeWidth={1.4} />
            </div>
            <h1 className="welcome-title">AXIOM</h1>
            <p className="welcome-sub">Чем Axiom может помочь?</p>
            <div className="welcome-model">
              <Cpu size={13} strokeWidth={1.8} />
              <span>{modelName ?? "модель не выбрана"}</span>
              {modelCapabilities.length > 0 && (
                <span className="welcome-caps">{modelCapabilities.join(" · ")}</span>
              )}
            </div>
            {globalChat && (
              <div className="welcome-global" title="Файловые и терминальные инструменты отключены">
                <Globe size={12} strokeWidth={1.8} />
                <span>Глобальный чат — проект не активен, инструменты файлов выключены</span>
              </div>
            )}
            <div className="welcome-suggestions">
              {SUGGESTIONS.map((item, index) => (
                <button
                  key={item.text}
                  className="suggestion"
                  style={{ animationDelay: `${0.08 * index + 0.1}s` }}
                  onClick={() => onSuggestion(item.text, item.search)}
                  title={item.search ? "Отправит с принудительным веб-поиском" : "Отправить этот запрос"}
                >
                  {item.search && <Sparkles size={12} strokeWidth={1.8} />}
                  {item.text}
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
      <div className="chat-inner">
        {messages.map((message) =>
          message.role === "user" ? (
            <UserMessage
              key={message.id}
              message={message}
              editable={message.id === lastUserId && !generating}
              onEdit={stable.onEdit}
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
              onStop={stable.onStop}
              onContinue={stable.onContinue}
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
}: {
  message: LiveMessage;
  editable: boolean;
  onEdit: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editing) return;
    const area = areaRef.current;
    if (!area) return;
    area.focus();
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
  }, [editing]);

  return (
    <div className={"msg user" + (editing ? " editing" : "")}>
      {!editing && (
        <div className="msg-head">
          <span className="msg-role">YOU</span>
          {editable && (
            <div className="msg-tools">
              <button
                className="msg-action"
                title="Изменить и отправить заново"
                onClick={() => {
                  setDraft(message.content);
                  setEditing(true);
                }}
              >
                <Pencil size={13} strokeWidth={1.9} />
                <span>Изменить</span>
              </button>
            </div>
          )}
        </div>
      )}

      {message.images && message.images.length > 0 && (
        <div className="msg-images">
          {message.images.map((image, index) => (
            <img key={index} src={image} alt={`вложение ${index + 1}`} />
          ))}
        </div>
      )}

      {editing ? (
        <div className="edit-box">
          <div className="edit-label">
            <Pencil size={12} strokeWidth={2} />
            <span>Редактирование сообщения</span>
            <span className="edit-label-note">ответ ниже будет сгенерирован заново</span>
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
              <kbd>Ctrl+Enter</kbd> — отправить · <kbd>Esc</kbd> — отмена
            </span>
            <div className="edit-actions-btns">
              <button className="btn ghost small" onClick={() => setEditing(false)}>
                Отмена
              </button>
              <button
                className="btn primary small"
                disabled={!draft.trim()}
                onClick={() => {
                  setEditing(false);
                  onEdit(draft);
                }}
              >
                Отправить заново
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
  onStop,
  onContinue,
}: {
  message: LiveMessage;
  config: AxiomConfig | null;
  generating: boolean;
  liveState: string;
  statusText: string | null;
  elapsedMs: number;
  onOpen: (url: string) => void;
  onStop: () => void;
  onContinue: () => void;
}) {
  const streaming = message.streaming;
  const cancelled = message.metrics?.state === "cancelled";
  const failed = message.metrics?.state === "error" || !!message.error;

  return (
    <div className="msg assistant">
      <div className="msg-head">
        <span className="msg-role">AXIOM</span>
        {streaming && (
          <span className="live-pill">
            <span className="live-dot" />
            <span>{statusText ?? liveStateLabel(liveState)}</span>
            <span className="live-sep" />
            <span className="live-time">{formatElapsed(elapsedMs)}</span>
            {generating && (
              <button className="stop-inline" onClick={onStop} title="Остановить (Esc)">
                <Square size={10} strokeWidth={2.2} fill="currentColor" />
              </button>
            )}
          </span>
        )}
        {message.content && !streaming && (
          <div className="msg-tools">
            <CopyIconButton text={message.content} title="Копировать ответ" />
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

      {!streaming && cancelled && (
        <div className="msg-note cancelled-resume">
          {message.content ? (
            <button
              className="resume-btn"
              onClick={onContinue}
              disabled={generating}
              title="Продолжить генерацию с места остановки"
            >
              <Play size={12} strokeWidth={2} fill="currentColor" />
              <span>Продолжить генерацию</span>
            </button>
          ) : (
            <>
              <Square size={12} strokeWidth={2} />
              <span>Генерация остановлена</span>
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
              ? "Агент остановился после лимита tool rounds"
              : "Генерация завершена с ошибкой"}
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
            <span>загрузка {(message.metrics.loadMs / 1000).toFixed(1)}s</span>
          )}
          {message.metrics.durationMs > 0 && <span>{formatElapsed(message.metrics.durationMs)}</span>}
        </div>
      )}
    </div>
  );
});

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
        title={open ? "Свернуть размышления" : "Показать размышления"}
      >
        <span className="think-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="think-title">{active ? "Размышляет" : "Процесс размышления"}</span>
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