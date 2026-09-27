import type { ReactNode, RefObject } from "react";
import { useMemo, useEffect, useRef, useState } from "react";
import { ArrowUp, CornerDownLeft, Globe, Image as ImageIcon, Loader2, Square, X } from "lucide-react";
import type { AxiomConfig } from "../types";
import { matchingCommands, type SlashCommand } from "../lib/commands";
import { readPromptHistory, writePromptHistory } from "../lib/composerStorage";
import { formatCount } from "../lib/format";
import Presence from "./Presence";

interface Props {
  generating: boolean;
  disabled: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: (text: string, forceSearch: boolean, images: string[]) => void;
  onCommand: (input: string) => void;
  onCancel: () => void;
  webSearchEnabled: boolean;
  onToggleWebSearch: () => void;
  config: AxiomConfig | null;
  modelName: string | null;
  modelSupportsVision: boolean | null;
  context: { used: number | null; window: number | null; ratio: number | null };
  onOpenContext: () => void;
  composerRef: RefObject<HTMLTextAreaElement>;
  workspaceFiles: string[];
  chatId: string | null;
  /** Compact model selector rendered inside the composer row. */
  modelSelector?: ReactNode;
}


/** Read an image file as a data URL (rendered directly in the composer). */
function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(`Не удалось прочитать ${file.name}`));
    reader.readAsDataURL(file);
  });
}

function imageFiles(list: FileList | null | undefined): File[] {
  return Array.from(list ?? []).filter((file) => file.type.startsWith("image/"));
}

export default function Composer(props: Props) {
  const {
    generating,
    disabled,
    draft,
    onDraftChange,
    onSend,
    onCommand,
    onCancel,
    webSearchEnabled,
    onToggleWebSearch,
    modelSupportsVision,
    context,
    onOpenContext,
    composerRef,
    workspaceFiles,
    chatId,
  } = props;

  const MAX_IMAGES = 3;
  const MAX_FILE_BYTES = 10 * 1024 * 1024;

  const [images, setImages] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [mentionStart, setMentionStart] = useState<number | null>(null);
  const [promptHistory, setPromptHistory] = useState<string[]>(() => readPromptHistory(chatId));
  const [historyCursor, setHistoryCursor] = useState<number | null>(null);
  const historyDraftRef = useRef("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setPromptHistory(readPromptHistory(chatId));
    setHistoryCursor(null);
    historyDraftRef.current = "";
  }, [chatId]);

  const mentionMatches = useMemo(() => {
    if (mentionStart === null || workspaceFiles.length === 0) return [];
    const token = draft.slice(mentionStart + 1).match(/^[^\\s@]*/)?.[0] ?? "";
    const query = token.toLowerCase();
    return workspaceFiles
      .filter((file) => file.toLowerCase().includes(query))
      .slice(0, 12);
  }, [draft, mentionStart, workspaceFiles]);

  useEffect(() => {
    const cursor = composerRef.current?.selectionStart;
    if (cursor === undefined || workspaceFiles.length === 0) return;
    const before = draft.slice(0, cursor);
    const match = before.match(/(?:^|\\s)@([^\\s@]*)$/);
    if (!match) {
      setMentionStart(null);
      return;
    }
    const at = before.lastIndexOf("@", cursor);
    setMentionStart(at);
    setMentionIndex(0);
  }, [draft, composerRef, workspaceFiles.length]);

  const commands = useMemo<SlashCommand[]>(() => {
    const trimmed = draft.trim();
    if (!trimmed.startsWith("/")) return [];
    return matchingCommands(trimmed);
  }, [draft]);

  useEffect(() => {
    setPaletteOpen(commands.length > 0);
    setPaletteIndex(0);
  }, [commands]);

  useEffect(() => {
    if (!paletteOpen && mentionMatches.length === 0) return;
    const close = (e: MouseEvent | PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setPaletteOpen(false);
        setMentionStart(null);
      }
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("mousedown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("mousedown", close);
    };
  }, [paletteOpen, mentionMatches.length]);

  // Auto-grow the textarea up to a sane ceiling.
  useEffect(() => {
    const area = composerRef.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 232)}px`;
  }, [draft, composerRef, workspaceFiles.length]);

  const flash = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice((current) => (current === message ? null : current)), 3400);
  };

  const addFiles = async (files: File[]) => {
    if (!files.length) return;
    if (modelSupportsVision === false) {
      flash("Текущая модель не поддерживает изображения — переключитесь на vision-модель");
      return;
    }
    const room = MAX_IMAGES - images.length;
    if (room <= 0) {
      flash(`Максимум ${MAX_IMAGES} изображения`);
      return;
    }
    const encoded: string[] = [];
    for (const file of files.slice(0, room)) {
      if (file.size > MAX_FILE_BYTES) {
        flash(`${file.name || "изображение"}: больше 10 МБ`);
        continue;
      }
      try {
        encoded.push(await fileToDataUrl(file));
      } catch (err) {
        flash(String(err));
      }
    }
    if (encoded.length) setImages((current) => [...current, ...encoded].slice(0, MAX_IMAGES));
  };

  const submit = (forceSearch = false) => {
    if (generating || disabled) return;
    const text = draft.trim();
    if (!text && images.length === 0) return;
    if (text.startsWith("/") && !images.length) {
      setPaletteOpen(false);
      onDraftChange("");
      void onCommand(text);
      return;
    }
    if (text) {
      setPromptHistory((current) => {
        const next = current[current.length - 1] === text ? current : [...current, text].slice(-100);
        writePromptHistory(chatId, next);
        return next;
      });
      setHistoryCursor(null);
    }
    onSend(text, forceSearch, images);
    onDraftChange("");
    setImages([]);
    setPaletteOpen(false);
  };

  const acceptCommand = (command: SlashCommand) => {
    const needsArgument = command.argumentHint != null;
    setPaletteOpen(false);
    if (!needsArgument) {
      onDraftChange("");
      void onCommand(command.name);
    } else {
      onDraftChange(`${command.name} `);
    }
    composerRef.current?.focus();
  };

  const acceptMention = (file: string) => {
    if (mentionStart === null) return;
    const cursor = composerRef.current?.selectionStart ?? draft.length;
    const after = draft.slice(cursor);
    const before = draft.slice(0, mentionStart);
    onDraftChange(`${before}@${file} ${after}`);
    setMentionStart(null);
    window.setTimeout(() => composerRef.current?.focus(), 0);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionMatches.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setMentionIndex((index) => Math.min(index + 1, mentionMatches.length - 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setMentionIndex((index) => Math.max(index - 1, 0));
        return;
      }
      if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
        event.preventDefault();
        acceptMention(mentionMatches[mentionIndex]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setMentionStart(null);
        return;
      }
    }
    if (paletteOpen && commands.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setPaletteIndex((index) => Math.min(commands.length - 1, index + 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setPaletteIndex((index) => Math.max(0, index - 1));
        return;
      }
      if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
        event.preventDefault();
        const selected = commands[paletteIndex];
        if (selected) {
          // A command with an argument is only being completed when the user
          // accepts a suggestion. If an argument is already present, Enter
          // must execute the command instead of repeatedly reinserting it.
          if (event.key === "Enter" && selected.argumentHint != null
            && draft.trim() !== selected.name && draft.trim().startsWith(`${selected.name} `)) {
            const commandText = draft.trim();
            onDraftChange("");
            void onCommand(commandText);
          } else {
            acceptCommand(selected);
          }
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setPaletteOpen(false);
        return;
      }
    }
    if (!paletteOpen && mentionMatches.length === 0 && promptHistory.length > 0) {
      const area = event.currentTarget;
      const atStart = area.selectionStart === 0 && area.selectionEnd === 0;
      const atEnd = area.selectionStart === draft.length && area.selectionEnd === draft.length;
      if (event.key === "ArrowUp" && atStart && (historyCursor !== null || !draft.includes("\n"))) {
        event.preventDefault();
        if (historyCursor === null) historyDraftRef.current = draft;
        const next = historyCursor === null ? promptHistory.length - 1 : Math.max(0, historyCursor - 1);
        setHistoryCursor(next);
        onDraftChange(promptHistory[next] ?? "");
        window.setTimeout(() => {
          const input = composerRef.current;
          input?.setSelectionRange(input.value.length, input.value.length);
        }, 0);
        return;
      }
      if (event.key === "ArrowDown" && historyCursor !== null && atEnd) {
        event.preventDefault();
        const next = historyCursor + 1;
        if (next >= promptHistory.length) {
          setHistoryCursor(null);
          onDraftChange(historyDraftRef.current);
        } else {
          setHistoryCursor(next);
          onDraftChange(promptHistory[next] ?? "");
        }
        window.setTimeout(() => {
          const input = composerRef.current;
          input?.setSelectionRange(input.value.length, input.value.length);
        }, 0);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey) {
      event.preventDefault();
      if (draft.trim().startsWith("/") && !images.length) {
        onCommand(draft.trim());
        onDraftChange("");
        return;
      }
      submit(false);
    }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit(true);
    }
  };

  const estimate = Math.max(1, Math.round((draft.length + images.length * 1200) / 4));

  return (
    <div className="composer-area" ref={containerRef}>
      <Presence open={mentionMatches.length > 0}>
        <div className="mention-palette" role="listbox" aria-label="Файлы проекта">
          <div className="mention-palette-head">ФАЙЛЫ ПРОЕКТА</div>
          {mentionMatches.map((file, index) => (
            <button
              key={file}
              className={"mention-item" + (index === mentionIndex ? " cursor" : "")}
              onMouseEnter={() => setMentionIndex(index)}
              onClick={() => acceptMention(file)}
            >
              <span>{file}</span>
              <kbd>Tab</kbd>
            </button>
          ))}
        </div>
      </Presence>
      <Presence open={paletteOpen}>
        <div className="palette" role="listbox">
          <div className="palette-head">COMMANDS</div>
          {commands.map((command, index) => (
            <button
              key={command.name}
              role="option"
              aria-selected={index === paletteIndex}
              className={"palette-item" + (index === paletteIndex ? " cursor" : "")}
              onMouseEnter={() => setPaletteIndex(index)}
              onClick={() => acceptCommand(command)}
            >
              <span className="palette-name">
                {command.name}
                {command.argumentHint ? <span className="palette-arg"> {command.argumentHint}</span> : null}
              </span>
              <span className="palette-desc">{command.description}</span>
            </button>
          ))}
          <div className="palette-foot">
            <CornerDownLeft size={11} strokeWidth={2} /> выбрать · ↑↓ навигация · Esc закрыть
          </div>
        </div>
      </Presence>

      <div className={"composer" + (images.length > 0 ? " has-attach" : "") + (generating ? " generating" : "")}>
        {notice && <div className="composer-notice">{notice}</div>}

        {images.length > 0 && (
          <div className="attach-row inline">
            {images.map((image, index) => (
              <div className="attach-thumb" key={index}>
                <img src={image} alt={`вложение ${index + 1}`} />
                <button
                  className="attach-remove"
                  onClick={() => setImages((prev) => prev.filter((_, i) => i !== index))}
                  title="Убрать изображение"
                >
                  <X size={12} strokeWidth={2.2} />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={composerRef}
          rows={1}
          placeholder={
            disabled ? "Ollama недоступна — проверьте подключение" : "Спросите Axiom…  / — команды, ↑↓ — история"
          }
          value={draft}
          onChange={(event) => {
            setHistoryCursor(null);
            onDraftChange(event.target.value);
          }}
          onKeyDown={onKeyDown}
          onPaste={(event) => {
            const files = imageFiles(event.clipboardData?.files);
            if (files.length) {
              event.preventDefault();
              void addFiles(files);
            }
          }}
          onDrop={(event) => {
            const files = imageFiles(event.dataTransfer?.files);
            if (files.length) {
              event.preventDefault();
              void addFiles(files);
            }
          }}
          disabled={disabled}
          spellCheck={false}
        />

        <div className="composer-row">
          <div className="composer-left">
            {props.modelSelector}
            <button
              className={"chip" + (webSearchEnabled ? " on" : "")}
              onClick={onToggleWebSearch}
              title="Веб-поиск: агент ищет в интернете, если нужно"
            >
              <Globe size={13} strokeWidth={1.8} />
              <span>Web Search</span>
              <span className={"chip-dot" + (webSearchEnabled ? " on" : "")} />
            </button>
            {modelSupportsVision !== false && (
              <label className="chip ghost" title="Прикрепить изображение (Ctrl+V или drag & drop)">
                <ImageIcon size={13} strokeWidth={1.8} />
                <span>Фото</span>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(event) => {
                    void addFiles(imageFiles(event.target.files));
                    event.target.value = "";
                  }}
                />
              </label>
            )}
          </div>

          <div className="composer-right">
            <button className="ctx-chip" onClick={onOpenContext} title="Контекст: токены, сообщения, инструменты">
              {context.used != null || context.window != null ? (
                <span>
                  {formatCount(context.used)} / {formatCount(context.window)} tok
                </span>
              ) : (
                <span>ctx —</span>
              )}
            </button>
            <span className="token-counter" title="Оценка токенов запроса">
              ~{estimate} tok
            </span>
            {generating ? (
              <button className="send-btn stop" onClick={onCancel} title="Остановить (Esc)">
                <Square size={13} strokeWidth={2} fill="currentColor" />
              </button>
            ) : (
              <button
                className="send-btn"
                onClick={() => submit()}
                disabled={(!draft.trim() && images.length === 0) || disabled}
                title="Отправить (Enter)"
              >
                {disabled ? <Loader2 size={15} className="spin" /> : <ArrowUp size={16} strokeWidth={2.2} />}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
