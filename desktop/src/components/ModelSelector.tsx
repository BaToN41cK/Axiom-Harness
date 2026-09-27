import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Cpu, Eye, Loader2, RefreshCw, Sparkles, Wrench, AlertTriangle, X } from "lucide-react";
import type { ModelInfo } from "../types";
import { formatBytes, formatCount } from "../lib/format";
import Presence from "./Presence";

interface Props {
  models: ModelInfo[];
  active: ModelInfo | null;
  loading: boolean;
  error: string | null;
  switching: string | null;
  disabled: boolean;
  openSignal: number;
  onSelect: (name: string, providerId?: string) => Promise<boolean>;
  onRefresh: () => void;
}

const CAPABILITY_LABELS: { key: string; label: string; icon: typeof Eye }[] = [
  { key: "thinking", label: "Reasoning", icon: Eye },
  { key: "tools", label: "Tools", icon: Wrench },
  { key: "vision", label: "Vision", icon: Sparkles },
];

const PROVIDER_LABELS: Record<string, string> = {
  ollama: "Ollama",
  openai_compatible: "OpenAI Compatible",
  anthropic: "Anthropic",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  deepseek: "DeepSeek",
  gemini: "Gemini",
  mistral: "Mistral",
};

function providerLabel(providerId: string): string {
  return PROVIDER_LABELS[providerId] ?? providerId.replaceAll("_", " ");
}

/** Describes a model in the words Ollama actually supports. */
function describe(model: ModelInfo): string {
  if (model.capabilities.includes("thinking")) return "Reasoning model";
  if (model.capabilities.includes("tools")) return "Tool-capable model";
  if (model.capabilities.includes("vision")) return "Vision model";
  if (model.capabilities.length) return "General model";
  return "Возможности неизвестны";
}

export default function ModelSelector(props: Props) {
  const { models, active, loading, error, switching, disabled, openSignal, onSelect, onRefresh } = props;
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!openSignal) return;
    setOpen((prev) => {
      const next = !prev;
      if (next) onRefresh();
      return next;
    });
  }, [openSignal, onRefresh]);

  useEffect(() => {
    if (!open) return;
    const onGlobalKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      }
    };
    const close = (event: MouseEvent | PointerEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onGlobalKeyDown, true);
    window.addEventListener("pointerdown", close);
    window.addEventListener("mousedown", close);
    return () => {
      window.removeEventListener("keydown", onGlobalKeyDown, true);
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("mousedown", close);
    };
  }, [open]);

  const items = useMemo(() => models, [models]);

  useEffect(() => {
    if (!open) return;
    const index = items.findIndex((m) => m.name === active?.name
      && (m.providerId ?? "ollama") === (active.providerId ?? "ollama"));
    setCursor(index >= 0 ? index : 0);
  }, [open, items, active?.name, active?.providerId]);

  const choose = async (name: string, providerId = "ollama") => {
    setSelectionError(null);
    const selected = await onSelect(name, providerId);
    if (selected) setOpen(false);
    else setSelectionError(`Не удалось выбрать ${providerId}/${name}. Проверьте провайдера, endpoint и API-ключ.`);
  };

  const busy = switching != null;

  /** Keyboard navigation of both the toggle and the open list. */
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "Enter") {
        event.preventDefault();
        setOpen(true);
        onRefresh();
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(items.length - 1, c + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const target = items[cursor];
      if (target) choose(target.name, target.providerId ?? "ollama");
    }
  };

  return (
    <div className="model-selector" ref={boxRef} onKeyDown={onKeyDown}>
      <button
        className={"model-btn" + (open ? " open" : "") + (disabled ? " disabled" : "")}
        onClick={() => {
          setOpen((v) => !v);
          if (!open) onRefresh();
        }}
        title={active ? `${providerLabel(active.providerId ?? "ollama")} · ${active.name} — сменить модель` : "Выбрать модель"}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {busy ? <Loader2 size={14} className="spin" /> : <Cpu size={14} strokeWidth={1.8} />}
        <span className="model-btn-label" key={`${active?.providerId}/${active?.name}`}>{active?.displayName ?? "Модель не выбрана"}</span>
        {active && (
          <span className="model-btn-caps">
            {CAPABILITY_LABELS.filter((c) => active.capabilities.includes(c.key)).map((c) => (
              <c.icon key={c.key} size={12} strokeWidth={1.8} />
            ))}
          </span>
        )}
        <ChevronDown size={14} strokeWidth={1.8} className={"chevron" + (open ? " open" : "")} />
      </button>

      <Presence open={open}>
        <div className="model-menu" role="listbox">
          <div className="model-menu-head">
            <span>MODEL</span>
            <div className="model-menu-actions">
              <button className="icon-btn tiny" onClick={onRefresh} disabled={loading} title="Обновить список из Ollama">
                {loading ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} strokeWidth={1.8} />}
              </button>
              <button className="icon-btn tiny" onClick={() => setOpen(false)} title="Закрыть (Esc)">
                <X size={13} strokeWidth={1.8} />
              </button>
            </div>
          </div>

          {(error || selectionError) && (
            <div className="model-menu-error" role="alert">
              <AlertTriangle size={13} strokeWidth={1.9} />
              <span>{selectionError ?? error}</span>
            </div>
          )}

          <div className="model-menu-list">
            {!loading && items.length === 0 && !error && (
              <div className="model-menu-empty">
                Моделей пока нет. Установите через <code>ollama pull qwen3:8b</code> или подключите
                API-провайдера — список подтянется автоматически.
              </div>
            )}
            {items.map((model, index) => {
              const providerId = model.providerId ?? "ollama";
              const isExternal = providerId !== "ollama";
              const isActive = model.name === active?.name && providerId === (active.providerId ?? "ollama");
              const switchKey = `${providerId}/${model.name}`;
              const isSwitching = switching === switchKey || (!isExternal && switching === model.name);
              return (
                <button
                  key={switchKey}
                  role="option"
                  aria-selected={isActive}
                  className={"model-item" + (isActive ? " active" : "") + (index === cursor ? " cursor" : "")}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => choose(model.name, providerId)}
                >
                  <span className={"model-radio" + (isActive ? " on" : "")}>
                    {isSwitching ? (
                      <Loader2 size={11} className="spin" />
                    ) : isActive ? (
                      <Check size={11} strokeWidth={3} />
                    ) : null}
                  </span>
                  <span className="model-item-body">
                    <span className="model-item-title">
                      <span className="model-item-name">{model.displayName}</span>
                      <span className="model-item-state">
                        <span className={"dot" + (model.loaded ? " on" : "")} />
                        {isExternal ? `${providerLabel(providerId)} · API` : model.loaded ? "Ollama · готова" : "Ollama"}
                      </span>
                    </span>
                    <span className="model-item-sub">{describe(model)}</span>
                    <span className="model-item-meta">
                      {model.name}
                      {model.parameterSize ? ` · ${model.parameterSize}` : ""}
                      {model.quantization ? ` · ${model.quantization}` : ""}
                      {model.contextLength ? ` · ctx ${formatCount(model.contextLength)}` : ""}
                      {model.sizeBytes ? ` · ${formatBytes(model.sizeBytes)}` : ""}
                    </span>
                  </span>
                  <span className="model-item-caps">
                    {CAPABILITY_LABELS.map(({ key, icon: Icon, label }) => (
                      <span
                        key={key}
                        className={"cap" + (model.capabilities.includes(key) ? " on" : "")}
                        title={
                          model.capabilities.includes(key) ? label : `${label}: Ollama не сообщает поддержку`
                        }
                      >
                        <Icon size={12} strokeWidth={1.8} />
                      </span>
                    ))}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="model-menu-foot">
            Данные: Ollama <code>/api/tags</code> · <code>/api/ps</code> · <kbd>Esc</kbd> закрыть
          </div>
        </div>
      </Presence>
    </div>
  );
}