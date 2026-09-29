import { useState, useEffect, useRef, useId, createContext, useContext, isValidElement, cloneElement } from "react";
import {
  BookOpen,
  Brain,
  Globe,
  Info,
  Keyboard,
  MessageSquare,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import type {
  AxiomConfig,
  ProviderModelRow,
  ProviderRow,
  PluginRow,
  PluginInstallResult,
  SearchProviderChoice,
  SearchTestResult,
  MemoryRow,
  KnowledgeRow,
  KnowledgeHit,
} from "../types";
import type { SettingsSection } from "../hooks/useAxiom";
import { isSoundEnabled, playUiSound, setSoundEnabled } from "../lib/sound";
import type { UiSound } from "../lib/sound";
import "../styles/settings.css";

interface Props {
  config: AxiomConfig;
  section: SettingsSection;
  setSection: (section: SettingsSection) => void;
  onClose: () => void;
  onSave: (patch: Partial<AxiomConfig>) => void;
  onRestartCore: () => void;
  providerRows: ProviderRow[];
  providerModels: ProviderModelRow[];
  providerLoading: boolean;
  onProviderSaveSettings: (id: string, key: string, baseUrl: string) => Promise<void>;
  onProviderPickModel: (providerId: string, model: string) => Promise<void>;
  pluginRows: PluginRow[];
  pluginLoading: boolean;
  onLoadPlugins: () => Promise<void>;
  onInstallPlugin: () => Promise<PluginInstallResult | null>;
  onTogglePlugin: (name: string, enabled: boolean) => Promise<PluginRow | null>;
  onRemovePlugin: (name: string) => Promise<boolean>;
  bundledPlugins: PluginRow[];
  onInstallBundledPlugin: (name: string) => Promise<PluginInstallResult | null>;
  onLoadProviders: () => Promise<void>;
  searchProviders: SearchProviderChoice[];
  onLoadSearchProviders: () => Promise<void>;
  onRunSearchTest: (query: string) => Promise<SearchTestResult | null>;
  searchTestResult: SearchTestResult | null;
  searchTesting: boolean;
  // W2.1 Curated Memory — the user edits every persisted item here.
  memoryRows: MemoryRow[];
  memoryLoading: boolean;
  onLoadMemory: () => Promise<void>;
  onAddMemory: (content: string, category: string, scope: string) => Promise<boolean>;
  onEditMemory: (id: string, content: string) => Promise<boolean>;
  onDeleteMemory: (id: string) => Promise<boolean>;
  // W2.2 Knowledge Base — collections and cited search.
  knowledgeRows: KnowledgeRow[];
  knowledgeLoading: boolean;
  knowledgeHits: KnowledgeHit[];
  onLoadKnowledge: () => Promise<void>;
  onAddKnowledge: (name: string, path: string) => Promise<boolean>;
  onReindexKnowledge: (name: string) => Promise<boolean>;
  onRemoveKnowledge: (name: string) => Promise<boolean>;
  onSearchKnowledge: (query: string) => Promise<KnowledgeHit[]>;
}

const SECTIONS: { key: SettingsSection; label: string; icon: ReactNode }[] = [
  { key: "general", label: "Общие", icon: <Settings2 size={14} strokeWidth={1.8} /> },
  { key: "appearance", label: "Вид", icon: <Sparkles size={14} strokeWidth={1.8} /> },
  { key: "models", label: "Модели", icon: <SlidersHorizontal size={14} strokeWidth={1.8} /> },
  { key: "providers", label: "Провайдеры", icon: <Globe size={14} strokeWidth={1.8} /> },
  { key: "plugins", label: "Плагины", icon: <Wrench size={14} strokeWidth={1.8} /> },
  { key: "memory", label: "Память", icon: <Brain size={14} strokeWidth={1.8} /> },
  { key: "knowledge", label: "Знания", icon: <BookOpen size={14} strokeWidth={1.8} /> },
  { key: "chat", label: "Чат", icon: <MessageSquare size={14} strokeWidth={1.8} /> },
  { key: "tools", label: "Инструменты", icon: <Wrench size={14} strokeWidth={1.8} /> },
  { key: "shortcuts", label: "Горячие клавиши", icon: <Keyboard size={14} strokeWidth={1.8} /> },
  { key: "about", label: "О программе", icon: <Info size={14} strokeWidth={1.8} /> },
];

const SECTION_GROUPS: { label: string; keys: SettingsSection[] }[] = [
  { label: "Рабочее пространство", keys: ["general", "appearance", "chat", "shortcuts"] },
  { label: "AI и подключения", keys: ["models", "providers", "tools"] },
  { label: "Данные", keys: ["memory", "knowledge"] },
  { label: "Расширения", keys: ["plugins"] },
  { label: "Система", keys: ["about"] },
];

const SECTION_META: Record<SettingsSection, { eyebrow: string; title: string; description: string }> = {
  general: { eyebrow: "Рабочее пространство", title: "Общие", description: "История, системный промпт и базовое поведение AXIOM." },
  appearance: { eyebrow: "Рабочее пространство", title: "Вид", description: "Тема, акцент, плотность интерфейса и анимации." },
  chat: { eyebrow: "Рабочее пространство", title: "Чат", description: "Как AXIOM отображает и сопровождает поток ответа." },
  shortcuts: { eyebrow: "Рабочее пространство", title: "Горячие клавиши", description: "Быстрые команды для навигации и работы с диалогом." },
  models: { eyebrow: "AI и подключения", title: "Модели", description: "Ollama endpoint, reasoning и параметры генерации." },
  providers: { eyebrow: "AI и подключения", title: "Провайдеры", description: "Подключения к локальным моделям и внешним API." },
  tools: { eyebrow: "AI и подключения", title: "Инструменты", description: "Web search, файлы, terminal и режимы разрешений." },
  memory: { eyebrow: "Данные", title: "Память", description: "Сохранённые факты и предпочтения, доступные для редактирования." },
  knowledge: { eyebrow: "Данные", title: "Знания", description: "Коллекции документов и цитируемый локальный поиск." },
  plugins: { eyebrow: "Расширения", title: "Плагины", description: "Установка, доверие и управление кодом расширений AXIOM." },
  about: { eyebrow: "Система", title: "О программе", description: "Локальная архитектура AXIOM и сведения о безопасности." },
};

/** Settings-local dialog focus scope; nested confirmations take precedence. */
function useSettingsFocus(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const previous = document.activeElement as HTMLElement | null;
    const items = () => Array.from(node.querySelectorAll<HTMLElement>(
      "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex='0']",
    )).filter((el) => el.getClientRects().length && getComputedStyle(el).visibility !== "hidden" && !el.closest("[inert]"));
    (items()[0] ?? node).focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => {
      if (node.closest("[inert]") || node.querySelector('[role="dialog"]')) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        close.current();
      }
      if (event.key === "Tab") {
        const list = items();
        const first = list[0];
        const last = list[list.length - 1];
        if (!first) { event.preventDefault(); node.focus(); return; }
        if (!node.contains(document.activeElement) || (event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, []);
  return ref;
}

function SettingsConfirmation({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useSettingsFocus(onClose);
  const titleId = useId();
  return <div className="modal-backdrop settings-confirm-backdrop" onClick={(e) => { e.stopPropagation(); onClose(); }}>
    <div className="modal confirm settings-confirm" ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
      <div className="modal-head"><h2 id={titleId}>{title}</h2><button className="icon-btn" aria-label="Закрыть подтверждение" onClick={onClose}><X size={16} /></button></div>
      {children}
    </div>
  </div>;
}

const SHORTCUTS: { keys: [string, string] | string; label: string }[] = [
  { keys: "Ctrl+N", label: "Новый разговор" },
  { keys: "Ctrl+B", label: "Показать/скрыть боковую панель" },
  { keys: "Ctrl+K", label: "Поиск по разговорам" },
  { keys: "Ctrl+,", label: "Настройки" },
  { keys: "Ctrl+/", label: "Фокус в поле ввода" },
  { keys: "Enter", label: "Отправить сообщение" },
  { keys: "Shift+Enter", label: "Перенос строки" },
  { keys: "Ctrl+Enter", label: "Отправить с веб-поиском" },
  { keys: "Esc", label: "Остановить генерацию / закрыть окно" },
  { keys: "Ctrl+V", label: "Вставить изображение (vision-модели)" },
];

export default function SettingsModal({
  config,
  section,
  setSection,
  onClose,
  onSave,
  onRestartCore,
  providerRows,
  providerModels,
  providerLoading,
  onProviderSaveSettings,
  onProviderPickModel,
  onLoadProviders,
  pluginRows,
  pluginLoading,
  onLoadPlugins,
  onInstallPlugin,
  onTogglePlugin,
  onRemovePlugin,
  bundledPlugins,
  onInstallBundledPlugin,
  searchProviders,
  onLoadSearchProviders,
  onRunSearchTest,
  searchTestResult,
  searchTesting,
  memoryRows,
  memoryLoading,
  onLoadMemory,
  onAddMemory,
  onEditMemory,
  onDeleteMemory,
  knowledgeRows,
  knowledgeLoading,
  knowledgeHits,
  onLoadKnowledge,
  onAddKnowledge,
  onReindexKnowledge,
  onRemoveKnowledge,
  onSearchKnowledge,
}: Props) {
  const [draft, setDraft] = useState<AxiomConfig>(config);
  const dialogRef = useSettingsFocus(onClose);
  const contentRef = useRef<HTMLElement>(null);
  const meta = SECTION_META[section];

  useEffect(() => {
    setDraft(config);
  }, [config]);

  useEffect(() => {
    if (section === "providers") void onLoadProviders();
    if (section === "plugins") void onLoadPlugins();
    if (section === "tools") void onLoadSearchProviders();
    if (section === "memory") void onLoadMemory();
    if (section === "knowledge") void onLoadKnowledge();
  }, [section]);

  useEffect(() => { if (contentRef.current) contentRef.current.scrollTop = 0; }, [section]);

  const set = <K extends keyof AxiomConfig>(key: K, value: AxiomConfig[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const save = () => {
    const patch: Partial<AxiomConfig> = {
      ollama_url: draft.ollama_url,
      model: draft.model,
      web_search_enabled: draft.web_search_enabled,
      workspace_tools_enabled: draft.workspace_tools_enabled,
      workspace_root: draft.workspace_root,
      access_mode: draft.access_mode,
      terminal_enabled: draft.terminal_enabled,
      search_provider: draft.search_provider,
      search_max_sources: Number(draft.search_max_sources),
      search_read_sources: Number(draft.search_read_sources),
      search_timeout: Number(draft.search_timeout),
      history_limit: Number(draft.history_limit),
      show_reasoning: draft.show_reasoning,
      reasoning_expanded: draft.reasoning_expanded,
      theme: draft.theme,
      accent: draft.accent,
      panel_hover: draft.panel_hover,
      animations: draft.animations,
      save_history: draft.save_history,
      temperature: draft.temperature === null ? null : Number(draft.temperature),
      system_prompt: draft.system_prompt,
      think: draft.think,
      thinking_mode: draft.thinking_mode,
      keep_alive: draft.keep_alive,
      warmup_model: draft.warmup_model,
      num_ctx: draft.num_ctx === null ? null : Number(draft.num_ctx),
      num_predict: draft.num_predict === null ? null : Number(draft.num_predict),
      context_messages: Number(draft.context_messages),
      density: draft.density,
      font_size: Number(draft.font_size),
      sidebar_open: draft.sidebar_open,
      sidebar_width: Number(draft.sidebar_width),
      render_markdown: draft.render_markdown,
      auto_scroll: draft.auto_scroll,
      show_metrics: draft.show_metrics,
      show_context: draft.show_context,
      permission_mode: draft.permission_mode,
      autonomy_mode: draft.autonomy_mode,
      router_enabled: draft.router_enabled,
    };
    onSave(patch);
    onClose();
  };

  return (
    <div className="modal-backdrop axiom-settings-backdrop" onClick={onClose}>
      <div className="modal axiom-settings" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="axiom-settings-title" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="axiom-settings-head">
          <h2 id="axiom-settings-title"><span className="settings-wordmark">AXIOM</span>Настройки</h2>
          <button className="icon-btn" aria-label="Закрыть настройки" title="Закрыть (Esc)" onClick={onClose}>
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>

        <div className="axiom-settings-workspace">
          <nav className="settings-nav" aria-label="Разделы настроек">
            {SECTION_GROUPS.map((group) => (
              <div className="settings-nav-group" key={group.label}>
                <div className="settings-nav-group-label">{group.label}</div>
                {group.keys.map((key) => {
                  const item = SECTIONS.find((candidate) => candidate.key === key)!;
                  return (
                    <button
                      key={item.key}
                      data-section={item.key}
                      className={"settings-nav-item" + (section === item.key ? " active" : "")}
                      aria-current={section === item.key ? "page" : undefined}
                      onClick={() => { if (section !== item.key) playUiSound("panel"); setSection(item.key); }}
                    >
                      <span className="settings-nav-icon">{item.icon}</span>
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          <main className="settings-main" ref={contentRef} aria-labelledby="settings-section-heading" tabIndex={0}>
            <header className="settings-section-title">
              <div>
                <h3 id="settings-section-heading">{meta.title}</h3>
                <p>{meta.description}</p>
              </div>
            </header>
            <div className="settings-content" key={section}>
            {section === "general" && <GeneralSection draft={draft} set={set} />}
            {section === "models" && <ModelsSection draft={draft} set={set} config={config} onRestartCore={onRestartCore} />}
            {section === "providers" && <ProvidersSection rows={providerRows} models={providerModels} loading={providerLoading} onSave={onProviderSaveSettings} onPickModel={onProviderPickModel} />}
            {section === "plugins" && <PluginsSection rows={pluginRows} bundled={bundledPlugins} loading={pluginLoading} onInstall={onInstallPlugin} onInstallBundled={onInstallBundledPlugin} onToggle={onTogglePlugin} onRemove={onRemovePlugin} />}
            {section === "memory" && <MemorySection rows={memoryRows} loading={memoryLoading} onLoad={onLoadMemory} onAdd={onAddMemory} onEdit={onEditMemory} onDelete={onDeleteMemory} />}
            {section === "knowledge" && (
              <KnowledgeSection
                rows={knowledgeRows}
                loading={knowledgeLoading}
                hits={knowledgeHits}
                onLoad={onLoadKnowledge}
                onAdd={onAddKnowledge}
                onReindex={onReindexKnowledge}
                onRemove={onRemoveKnowledge}
                onSearch={onSearchKnowledge}
              />
            )}
            {section === "chat" && <ChatSection draft={draft} set={set} />}
            {section === "tools" && <ToolsSection draft={draft} set={set} searchProviders={searchProviders} onRunSearchTest={onRunSearchTest} searchTestResult={searchTestResult} searchTesting={searchTesting} />}
            {section === "appearance" && <AppearanceSection draft={draft} set={set} />}
            {section === "shortcuts" && <ShortcutsSection />}
            {section === "about" && <AboutSection />}
            </div>
          </main>
        </div>

        <div className="axiom-settings-foot">
          <button className="btn ghost settings-restart" onClick={onRestartCore}>
            <RefreshCw size={14} strokeWidth={1.8} />
            <span>Перезапустить ядро</span>
          </button>
          <span className="settings-save-hint">{["providers", "plugins", "memory", "knowledge"].includes(section) ? "Действия в этом разделе применяются сразу" : "Параметры применяются кнопкой «Сохранить»"}</span>
          <div className="modal-foot-spacer" />
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn primary settings-save" onClick={save}>
            Сохранить
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ sections

interface SectionProps {
  draft: AxiomConfig;
  set: <K extends keyof AxiomConfig>(key: K, value: AxiomConfig[K]) => void;
}
function ProvidersSection({ rows, models, loading, onSave, onPickModel }: {
  rows: ProviderRow[]; models: ProviderModelRow[]; loading: boolean;
  onSave: (id: string, key: string, baseUrl: string) => Promise<void>;
  onPickModel: (providerId: string, model: string) => Promise<void>;
}) {
  const [selected, setSelected] = useState(rows.find((item) => item.id === "openai_compatible")?.id ?? rows[0]?.id ?? "openai_compatible");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const row = rows.find((item) => item.id === selected) ?? rows[0];
  useEffect(() => {
    if (rows.length && !rows.some((item) => item.id === selected)) {
      setSelected(rows.find((item) => item.id === "openai_compatible")?.id ?? rows[0].id);
    }
  }, [rows, selected]);
  useEffect(() => setBaseUrl(row?.base_url || ""), [row?.id, row?.base_url]);
  const providerModels = models.filter((item) => item.provider_id === selected);
  return <div className="provider-settings">
    <div className="settings-card provider-picker-card">
      <div className="settings-card-head">
        <h4>Подключение</h4>
        {row && <span className="settings-status-pill">{row.status}</span>}
      </div>
      <label className="settings-field"><span>Провайдер</span><select value={selected} onChange={(e) => { setSelected(e.target.value); setKey(""); }}>
        {rows.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      {row && <div className="provider-summary"><span>{row.configured ? "Подключение настроено" : "Требуется настройка"}</span><code>{row.base_url || "endpoint не задан"}</code></div>}
    </div>
    <div className="settings-card">
      <div className="settings-field-grid">
        <label className="settings-field"><span>API key</span><input type="password" value={key} placeholder={row?.configured ? "•••••••• (сохранён)" : "Не задан"} onChange={(e) => setKey(e.target.value)} /></label>
        <label className="settings-field"><span>Base URL</span><input value={baseUrl} spellCheck={false} placeholder="https://api.example.com/v1" onChange={(e) => setBaseUrl(e.target.value)} /></label>
      </div>
      <div className="settings-card-foot"><span>Пустой ключ — оставить текущий. Endpoint: /v1.</span><button className="btn primary" disabled={!row || loading} onClick={() => void onSave(selected, key, baseUrl.trim())}>{loading ? "Проверка…" : "Сохранить и проверить"}</button></div>
    </div>
    <div className="settings-card">
      <label className="settings-field"><span>Модель для следующих запросов</span><select value="" onChange={(e) => { if (e.target.value) void onPickModel(selected, e.target.value); }}>
        <option value="">Выберите модель…</option>
        {providerModels.map((item) => <option key={item.id} value={item.model}>{item.label} · {item.capabilities.join(", ")}</option>)}
      </select></label>
      {!providerModels.length && <div className="settings-inline-note">Модели появятся после проверки подключения.</div>}
    </div>
  </div>;
}



function PluginsSection({
  rows,
  bundled,
  loading,
  onInstall,
  onInstallBundled,
  onToggle,
  onRemove,
}: {
  rows: PluginRow[];
  bundled: PluginRow[];
  loading: boolean;
  onInstall: () => Promise<PluginInstallResult | null>;
  onInstallBundled: (name: string) => Promise<PluginInstallResult | null>;
  onToggle: (name: string, enabled: boolean) => Promise<PluginRow | null>;
  onRemove: (name: string) => Promise<boolean>;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pendingTrust, setPendingTrust] = useState<{ plugin: PluginRow | null; action: "install" | "run"; run: () => Promise<unknown> } | null>(null);
  const [pendingRemove, setPendingRemove] = useState<PluginRow | null>(null);

  const requestTrust = (plugin: PluginRow | null, action: "install" | "run", run: () => Promise<unknown>) => {
    setPendingTrust({ plugin, action, run });
  };

  const acceptTrust = async () => {
    const pending = pendingTrust;
    setPendingTrust(null);
    if (pending) await pending.run();
  };

  const toggleExpand = (name: string) => {
    setExpanded((prev) => (prev === name ? null : name));
  };

  return (
    <div className="plugin-settings">
      <div className="settings-section-head">
        <div>
          <h3>Установленные <span className="settings-count">{rows.length}</span></h3>
        </div>
        <button className="btn primary" disabled={loading} onClick={() => requestTrust(null, "install", onInstall)}>
          {loading ? "Загрузка…" : "Установить из папки"}
        </button>
      </div>
      <div className="plugin-path-hint">
        Каталог установленных плагинов: <code>~/.axiom/plugins/</code>
      </div>
      {rows.length === 0 ? (
        <div className="settings-empty">Плагинов пока нет. Выберите папку своего плагина или установите встроенный ниже.</div>
      ) : (
        <div className="plugin-list">
          {rows.map((plugin) => (
            <div className="plugin-card" key={plugin.name}>
              <div className="plugin-card-main">
                <div className="plugin-card-title">
                  <span className={"plugin-status-dot" + (plugin.enabled ? " enabled" : "")} />
                  <strong>{plugin.name}</strong>
                  <span className="plugin-version">v{plugin.version}</span>
                  <span className={"settings-status-pill " + (plugin.enabled ? "ready" : "idle")}>{plugin.enabled ? "Включён" : "Выключен"}</span>
                  {plugin.bundled && <span className="plugin-version">встроенный</span>}
                  {plugin.readme && (
                    <button
                      className="btn ghost small"
                      onClick={() => toggleExpand(plugin.name)}
                      aria-expanded={expanded === plugin.name}
                      style={{ marginLeft: "auto" }}
                    >
                      <BookOpen size={13} />{expanded === plugin.name ? "Скрыть" : "Документация"}
                    </button>
                  )}
                </div>
                <div className="plugin-card-description">
                  {plugin.description || "Пользовательский плагин AXIOM"}
                </div>
                <div className="plugin-card-meta">
                  {plugin.author && <span>Автор: {plugin.author}</span>}
                  {plugin.tools.length > 0 && <span>Инструменты: {plugin.tools.join(", ")}</span>}
                  {plugin.skills.length > 0 && <span>Skills: {plugin.skills.join(", ")}</span>}
                </div>
                {plugin.readme && (
                  <div className={"plugin-disclosure" + (expanded === plugin.name ? " open" : "")} aria-hidden={expanded !== plugin.name}>
                  <div className="plugin-card-readme">
                    <pre>{plugin.readme}</pre>
                  </div>
                  </div>
                )}
              </div>
              <div className="plugin-card-actions">
                <button
                  className={"switch" + (plugin.enabled ? " on" : "")}
                  role="switch"
                  aria-label={`${plugin.enabled ? "Выключить" : "Включить"} ${plugin.name}`}
                  aria-checked={plugin.enabled}
                  disabled={loading}
                  onClick={() => plugin.enabled
                    ? void onToggle(plugin.name, false)
                    : requestTrust(plugin, "run", async () => onToggle(plugin.name, true))}
                >
                  <span className="switch-knob" />
                </button>
                <button className="btn danger ghost" disabled={loading} aria-label={`Удалить плагин ${plugin.name}`} onClick={() => setPendingRemove(plugin)}>
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {bundled.length > 0 && (
        <>
          <div className="settings-section-head">
            <div>
              <h3>Каталог AXIOM <span className="settings-count">{bundled.length}</span></h3>
              <p>Встроенные расширения. После установки остаются выключенными.</p>
            </div>
          </div>
          <div className="plugin-list">
            {bundled.map((plugin) => (
              <div className="plugin-card" key={plugin.name}>
                <div className="plugin-card-main">
                  <div className="plugin-card-title">
                    <span className="plugin-status-dot" />
                    <strong>{plugin.name}</strong>
                    <span className="plugin-version">v{plugin.version}</span>
                    <span className="plugin-version">каталог</span>
                    {plugin.readme && (
                      <button
                        className="btn ghost small"
                        onClick={() => toggleExpand(plugin.name)}
                        aria-expanded={expanded === plugin.name}
                        style={{ marginLeft: "auto" }}
                      >
                        <BookOpen size={13} />{expanded === plugin.name ? "Скрыть" : "Документация"}
                      </button>
                    )}
                  </div>
                  <div className="plugin-card-description">
                    {plugin.description || "Встроенный плагин AXIOM"}
                  </div>
                  <div className="plugin-card-meta">
                    {plugin.author && <span>Автор: {plugin.author}</span>}
                    {plugin.tools.length > 0 && <span>Инструменты: {plugin.tools.join(", ")}</span>}
                  </div>
                  {plugin.readme && (
                    <div className={"plugin-disclosure" + (expanded === plugin.name ? " open" : "")} aria-hidden={expanded !== plugin.name}>
                    <div className="plugin-card-readme">
                      <pre>{plugin.readme}</pre>
                    </div>
                    </div>
                  )}
                </div>
                <div className="plugin-card-actions">
                  <button className="btn primary" disabled={loading} onClick={() => requestTrust(plugin, "install", async () => onInstallBundled(plugin.name))}>
                    Установить
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="plugin-security-note">
        Код плагина выполняется с правами процесса AXIOM. Манифест и `ui.scopes` не ограничивают Python-доступ.
        Включение плагина означает согласие запускать его код в этой и следующих сессиях, пока плагин включён.
      </div>
      {pendingTrust && (
        <SettingsConfirmation title="Подтвердить доверие к плагину" onClose={() => setPendingTrust(null)}>
            <div className="modal-body">
              <strong>{pendingTrust.plugin ? `${pendingTrust.plugin.name} v${pendingTrust.plugin.version}` : "Плагин из выбранной папки"}</strong>
              {pendingTrust.plugin?.description && <p className="about-text">{pendingTrust.plugin.description}</p>}
              {pendingTrust.plugin?.tools.length ? <p className="about-text">Объявленные инструменты: {pendingTrust.plugin.tools.join(", ")}</p> : null}
              {pendingTrust.plugin?.capabilities.length ? <p className="about-text">Возможности манифеста: {pendingTrust.plugin.capabilities.join(", ")}</p> : null}
              {pendingTrust.plugin?.ui_block?.scopes?.length ? <p className="about-text">Заявленные UI scopes (не применяются как ограничения Python): {pendingTrust.plugin.ui_block.scopes.join(", ")}</p> : null}
              <p className="about-text">После импорта Python-код может действовать с правами пользователя и процесса AXIOM: читать и изменять доступные файлы, обращаться к сети, переменным окружения и запускать процессы. AXIOM не изолирует код плагина.</p>
              <p className="about-text">{pendingTrust.action === "run" ? "Подтвердите запуск этого кода. Разрешение сохраняется, пока плагин включён." : "Подтверждение разрешает только установку. Плагин останется выключенным; запуск потребует отдельного подтверждения."}</p>
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={() => setPendingTrust(null)}>Отмена</button>
              <div className="modal-foot-spacer" />
              <button className="btn danger" onClick={() => void acceptTrust()}>{pendingTrust.action === "run" ? "Доверять и запустить" : "Подтвердить установку"}</button>
            </div>
        </SettingsConfirmation>
      )}
      {pendingRemove && (
        <SettingsConfirmation title="Удалить плагин?" onClose={() => setPendingRemove(null)}>
          <div className="modal-body"><strong>{pendingRemove.name}</strong><p className="about-text">Плагин будет удалён из AXIOM. Его инструменты и расширения станут недоступны. Для повторного использования потребуется установка.</p></div>
          <div className="modal-foot"><button className="btn ghost" onClick={() => setPendingRemove(null)}>Отмена</button><div className="modal-foot-spacer" /><button className="btn danger" onClick={() => { const name = pendingRemove.name; setPendingRemove(null); void onRemove(name); }}>Удалить плагин</button></div>
        </SettingsConfirmation>
      )}
    </div>
  );
}


function MemorySection({
  rows,
  loading,
  onLoad,
  onAdd,
  onEdit,
  onDelete,
}: {
  rows: MemoryRow[];
  loading: boolean;
  onLoad: () => Promise<void>;
  onAdd: (content: string, category: string, scope: string) => Promise<boolean>;
  onEdit: (id: string, content: string) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
}) {
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("normal");
  const [scope, setScope] = useState("global");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const submit = async () => {
    if (!content.trim()) return;
    if (await onAdd(content.trim(), category, scope)) setContent("");
  };

  const startEdit = (row: MemoryRow) => {
    setEditing(row.id);
    setEditText(row.content);
  };

  const saveEdit = async (id: string) => {
    if (await onEdit(id, editText.trim())) setEditing(null);
  };

  return (
    <div className="memory-settings">
      <div className="settings-section-head">
        <div>
          <h3>Память</h3>
          <p>
            Факты и предпочтения, которые AXIOM помнит между запусками. Модель читает и пишет память
            только через инструменты, а всё, что здесь сохранено, можно изменить или удалить вручную.
          </p>
        </div>
        <button className="btn ghost" disabled={loading} onClick={() => void onLoad()}>
          <RefreshCw size={13} strokeWidth={1.8} />
          {loading ? "Обновление…" : "Обновить"}
        </button>
      </div>

      <div className="memory-form">
        <textarea
          className="memory-input"
          rows={2}
          placeholder="Например: в этом проекте тесты запускаются через pytest"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <div className="memory-form-controls">
          <select className="memory-select" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="normal">обычный факт</option>
            <option value="sensitive">личное предпочтение</option>
          </select>
          <select className="memory-select" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="global">глобально</option>
            <option value="project">в проекте</option>
          </select>
          <button className="btn primary" disabled={!content.trim()} onClick={() => void submit()}>
            Запомнить
          </button>
        </div>
        <div className="settings-row-hint">
          Категория «запрещённая» недоступна для записи: такие записи никогда не попадают на диск.
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="settings-empty">
          Память пуста. Добавьте факт вручную или попросите модель запомнить что-то в диалоге.
        </div>
      ) : (
        <div className="memory-list">
          {rows.map((row) => (
            <div className="memory-card" key={row.id}>
              <div className="memory-card-main">
                {editing === row.id ? (
                  <textarea
                    className="memory-input"
                    rows={2}
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                  />
                ) : (
                  <div className="memory-card-text">{row.content}</div>
                )}
                <div className="memory-card-meta">
                  <span className="memory-badge">{row.scope === "project" ? "проект" : "глобально"}</span>
                  <span className="memory-badge">
                    {row.category === "sensitive" ? "предпочтение" : "факт"}
                  </span>
                  {row.tags.map((tag) => (
                    <span className="memory-badge" key={tag}>
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>
              <div className="memory-card-actions">
                {editing === row.id ? (
                  <>
                    <button className="btn primary small" onClick={() => void saveEdit(row.id)}>
                      Сохранить
                    </button>
                    <button className="btn ghost small" onClick={() => setEditing(null)}>
                      Отмена
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn ghost small" onClick={() => startEdit(row)}>
                      Изменить
                    </button>
                    <button
                      className="btn danger small"
                      onClick={() => void onDelete(row.id)}
                      aria-label={`Удалить запись памяти: ${row.content}`}
                    >
                      Удалить
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function KnowledgeSection({
  rows,
  loading,
  hits,
  onLoad,
  onAdd,
  onReindex,
  onRemove,
  onSearch,
}: {
  rows: KnowledgeRow[];
  loading: boolean;
  hits: KnowledgeHit[];
  onLoad: () => Promise<void>;
  onAdd: (name: string, path: string) => Promise<boolean>;
  onReindex: (name: string) => Promise<boolean>;
  onRemove: (name: string) => Promise<boolean>;
  onSearch: (query: string) => Promise<KnowledgeHit[]>;
}) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState(false);

  const submitAdd = async () => {
    const trimmedName = name.trim() || path.trim().split(/[\\/]/).filter(Boolean).pop() || "collection";
    if (!path.trim()) return;
    if (await onAdd(trimmedName, path.trim())) {
      setName("");
      setPath("");
    }
  };

  const submitSearch = async () => {
    if (!query.trim()) return;
    setSearched(true);
    await onSearch(query.trim());
  };

  return (
    <div className="memory-settings">
      <div className="settings-section-head">
        <div>
          <h3>База знаний</h3>
          <p>
            Локальные папки и документы индексируются в SQLite/FTS5 (BM25 работает полностью
            офлайн). Эмбеддинги Ollama — необязательный слой переранжирования: когда они
            недоступны, статус честно показывает это. Модель получает только цитируемые фрагменты.
          </p>
        </div>
        <button className="btn ghost" disabled={loading} onClick={() => void onLoad()}>
          <RefreshCw size={13} strokeWidth={1.8} />
          {loading ? "Обновление…" : "Обновить"}
        </button>
      </div>

      <div className="memory-form">
        <div className="memory-form-controls">
          <input
            className="memory-input"
            placeholder="Имя коллекции (напр. docs)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="memory-input"
            placeholder="Путь к папке или файлу…"
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <button className="btn primary" disabled={!path.trim() || loading} onClick={() => void submitAdd()}>
            Индексировать
          </button>
        </div>
        <div className="settings-row-hint">
          Повторная индексация читает только изменённые файлы; секреты (.env, ключи) никогда
          не попадают в индекс.
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="settings-empty">
          Коллекций пока нет. Укажите папку выше — после индексации модель сможет искать
          по ней через инструмент knowledge_search.
        </div>
      ) : (
        <div className="memory-list">
          {rows.map((row) => (
            <div className="memory-card" key={row.name}>
              <div className="memory-card-main">
                <div className="memory-card-text">{row.name}</div>
                <div className="memory-card-meta">
                  <span className="memory-badge">{row.files} файлов</span>
                  <span className="memory-badge">{row.chunks} фрагментов</span>
                  <span className="memory-badge">эмбеддинги: {row.embeddings}</span>
                </div>
                <div className="settings-row-hint">{row.path}</div>
              </div>
              <div className="memory-card-actions">
                <button className="btn ghost small" disabled={loading} onClick={() => void onReindex(row.name)}>
                  Переиндексировать
                </button>
                <button className="btn danger small" onClick={() => void onRemove(row.name)}>
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="memory-form">
        <div className="memory-form-controls">
          <input
            className="memory-input"
            placeholder="Поисковый запрос по базе знаний…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submitSearch(); }}
          />
          <button className="btn ghost" disabled={!query.trim() || rows.length === 0} onClick={() => void submitSearch()}>
            <Search size={13} strokeWidth={1.8} />
            Найти
          </button>
        </div>
      </div>
      {searched && hits.length === 0 && (
        <div className="settings-empty">Фрагментов по запросу не найдено.</div>
      )}
      {hits.length > 0 && (
        <div className="memory-list">
          {hits.map((hit, index) => (
            <div className="memory-card" key={`${hit.collection}/${hit.source}:${index}`}>
              <div className="memory-card-main">
                <div className="memory-card-text">{hit.text}</div>
                <div className="memory-card-meta">
                  <span className="memory-badge">
                    [{index + 1}] {hit.collection}/{hit.source}:{hit.start_line}-{hit.end_line}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const RowLabel = createContext<string | undefined>(undefined);

/**
 * Cues the user can audition from Appearance → «Проверить звуки».
 *
 * Only the cues tied to a real agent event are listed: a finished answer, a
 * failure, a blocked tool call and a user stop. UI chrome sounds (panels,
 * settings) are intentionally not previewable — they are heard while clicking.
 */
const SOUND_PREVIEWS: { kind: UiSound; label: string }[] = [
  { kind: "complete", label: "Ответ готов" },
  { kind: "error", label: "Ошибка" },
  { kind: "permission", label: "Запрос разрешения" },
  { kind: "stopped", label: "Остановлено" },
];

function GroupTitle({ children }: { children: ReactNode }) {
  return <h4 className="settings-group-title">{children}</h4>;
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  const id = useId();
  const control = isValidElement(children) && typeof children.type === "string" && ["input", "select", "textarea"].includes(children.type)
    ? cloneElement(children as React.ReactElement<{ "aria-labelledby"?: string; "aria-describedby"?: string }>, { "aria-labelledby": id, "aria-describedby": hint ? `${id}-hint` : undefined })
    : children;
  return (
    <div className="settings-row">
      <div className="settings-row-text">
        <div className="settings-row-label" id={id}>{label}</div>
        {hint && <div className="settings-row-hint" id={`${id}-hint`}>{hint}</div>}
      </div>
      <div className="settings-row-control"><RowLabel.Provider value={label}>{control}</RowLabel.Provider></div>
    </div>
  );
}

function Toggle({ value, onChange, label }: { value: boolean | null; onChange: (v: boolean) => void; label?: string }) {
  const rowLabel = useContext(RowLabel);
  return (
    <button
      className={"switch" + (value ? " on" : "")}
      role="switch"
      aria-label={label ?? rowLabel}
      aria-checked={!!value}
      onClick={() => onChange(!value)}
    >
      <span className="switch-knob" />
    </button>
  );
}

function GeneralSection({ draft, set }: SectionProps) {
  return (
    <>
      <GroupTitle>История и хранение</GroupTitle>
      <Row label="Сохранять историю" hint="Разговоры хранятся локально в ~/.axiom">
        <Toggle value={draft.save_history} onChange={(v) => set("save_history", v)} />
      </Row>
      <Row label="Лимит истории" hint="Сколько последних разговоров хранить">
        <input
          type="number"
          min={0}
          max={500}
          value={draft.history_limit}
          onChange={(e) => set("history_limit", Number(e.target.value))}
        />
      </Row>
      <GroupTitle>Поведение ассистента</GroupTitle>
      <Row label="Temperature" hint="Пусто — значение модели по умолчанию">
        <input
          type="number"
          step={0.1}
          min={0}
          max={2}
          value={draft.temperature ?? ""}
          placeholder="auto"
          onChange={(e) => set("temperature", e.target.value === "" ? null : Number(e.target.value))}
        />
      </Row>
      <Row label="Системный промпт" hint="Пусто — встроенный промпт AXIOM">
        <textarea
          rows={3}
          value={draft.system_prompt ?? ""}
          placeholder="по умолчанию"
          onChange={(e) => set("system_prompt", e.target.value || null)}
        />
      </Row>
    </>
  );
}

function ModelsSection({ draft, set, config, onRestartCore }: SectionProps & { config: AxiomConfig; onRestartCore: () => void }) {
  return (
    <>
      <GroupTitle>Подключение к Ollama</GroupTitle>
      <Row label="Ollama URL" hint={`Текущее соединение: ${config.ollama_url}`}>
        <input
          value={draft.ollama_url}
          spellCheck={false}
          onChange={(e) => set("ollama_url", e.target.value)}
        />
      </Row>
      <GroupTitle>Рассуждение и генерация</GroupTitle>
      <Row label="Think-режим" hint="Уровень рассуждений: авто — решает ядро по запросу">
        <select
          value={
            draft.think === null || draft.think === false
              ? "auto"
              : draft.think === true
                ? "on"
                : draft.think
          }
          onChange={(e) => {
            const v = e.target.value;
            set(
              "think",
              v === "auto" ? null : v === "on" ? true : (v as "low" | "medium" | "high" | "max"),
            );
          }}
        >
          <option value="auto">Авто</option>
          <option value="on">Всегда</option>
          <option value="low">Низкий</option>
          <option value="medium">Средний</option>
          <option value="high">Высокий</option>
          <option value="max">Максимум</option>
        </select>
      </Row>
      <Row label="Режим мышления" hint="Пресет глубины reasoning, когда Think = Авто">
        <select
          value={draft.thinking_mode}
          onChange={(e) =>
            set("thinking_mode", e.target.value as AxiomConfig["thinking_mode"])
          }
        >
          <option value="auto">Авто (по запросу)</option>
          <option value="fast">Быстрый</option>
          <option value="normal">Обычный</option>
          <option value="deep">Глубокий</option>
        </select>
      </Row>
      <GroupTitle>Память и лимиты</GroupTitle>
      <Row label="Прогрев модели" hint="Загрузить модель в память сразу после старта">
        <Toggle value={draft.warmup_model} onChange={(v) => set("warmup_model", v)} />
      </Row>
      <Row label="Держать модель в памяти" hint='Ollama keep_alive, например "30m" или "1h"'>
        <input
          value={draft.keep_alive}
          spellCheck={false}
          onChange={(e) => set("keep_alive", e.target.value)}
        />
      </Row>
      <Row label="Контекстное окно" hint="Пусто — по умолчанию модели (num_ctx)">
        <input
          type="number"
          min={512}
          max={131072}
          step={512}
          value={draft.num_ctx ?? ""}
          placeholder="auto"
          onChange={(e) => set("num_ctx", e.target.value === "" ? null : Number(e.target.value))}
        />
      </Row>
      <Row label="Максимум ответа" hint="Лимит токенов генерации (num_predict), пусто — авто">
        <input
          type="number"
          min={16}
          max={131072}
          value={draft.num_predict ?? ""}
          placeholder="auto"
          onChange={(e) =>
            set("num_predict", e.target.value === "" ? null : Number(e.target.value))
          }
        />
      </Row>
      <Row label="Ядро AXIOM" hint="Перезапуск Python-ядра и повторная проверка Ollama">
        <button className="btn ghost" onClick={onRestartCore}>
          Перезапустить
        </button>
      </Row>
    </>
  );
}

function ChatSection({ draft, set }: SectionProps) {
  return (
    <>
      <GroupTitle>Отображение ответа</GroupTitle>
      <Row label="Markdown" hint="Рендеринг ответов в Markdown с подсветкой кода">
        <Toggle value={draft.render_markdown} onChange={(v) => set("render_markdown", v)} />
      </Row>
      <Row label="Показывать reasoning" hint="Отображать thinking-блоки модели, когда они есть">
        <Toggle value={draft.show_reasoning} onChange={(v) => set("show_reasoning", v)} />
      </Row>
      <Row label="Раскрывать reasoning" hint="Thinking-блоки развёрнуты по умолчанию">
        <Toggle value={draft.reasoning_expanded} onChange={(v) => set("reasoning_expanded", v)} />
      </Row>
      <Row label="Автоскролл" hint="Следить за потоком генерации">
        <Toggle value={draft.auto_scroll} onChange={(v) => set("auto_scroll", v)} />
      </Row>
      <GroupTitle>Контекст и метрики</GroupTitle>
      <Row label="Метрики ответа" hint="Время, токены, скорость после генерации">
        <Toggle value={draft.show_metrics} onChange={(v) => set("show_metrics", v)} />
      </Row>
      <Row label="Индикатор контекста" hint="Заполнение контекстного окна модели">
        <Toggle value={draft.show_context} onChange={(v) => set("show_context", v)} />
      </Row>
      <Row label="Сообщений в контексте" hint="Сколько последних сообщений отправлять модели">
        <input
          type="number"
          min={4}
          max={200}
          value={draft.context_messages}
          onChange={(e) => set("context_messages", Number(e.target.value))}
        />
      </Row>
    </>
  );
}

function ToolsSection({
  draft,
  set,
  searchProviders,
  onRunSearchTest,
  searchTestResult,
  searchTesting,
}: SectionProps & {
  searchProviders: SearchProviderChoice[];
  onRunSearchTest: (query: string) => Promise<SearchTestResult | null>;
  searchTestResult: SearchTestResult | null;
  searchTesting: boolean;
}) {
  const [testQuery, setTestQuery] = useState("AXIOM local AI");
  return (
    <>
      <GroupTitle>Поиск в интернете</GroupTitle>
      <Row label="Веб-поиск" hint="Инструмент поиска в интернете (требует сеть, остальное — локально)">
        <Toggle value={draft.web_search_enabled} onChange={(v) => set("web_search_enabled", v)} />
      </Row>
      <Row label="Движок поиска" hint="Auto — устойчивая цепочка; можно закрепить один движок">
        <select
          value={draft.search_provider}
          onChange={(e) => set("search_provider", e.target.value as AxiomConfig["search_provider"])}
        >
          {(searchProviders.length
            ? searchProviders
            : [{ id: "auto", name: "Auto" }]
          ).map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </Row>
      <Row label="Проверка поиска" hint="Реальный запрос: движок, задержка и результаты или ошибка">
        <div className="search-test-control">
          <input
            value={testQuery}
            aria-label="Запрос для проверки веб-поиска"
            spellCheck={false}
            placeholder="запрос"
            onChange={(e) => setTestQuery(e.target.value)}
          />
          <button
            className="btn ghost"
            disabled={searchTesting}
            onClick={() => void onRunSearchTest(testQuery)}
          >
            {searchTesting ? "Проверка…" : "Проверить"}
          </button>
        </div>
      </Row>
      {searchTestResult && (
        <div className={"search-test-result" + (searchTestResult.ok ? " ok" : " err")}>
          <div className="search-test-line">
            <span className="search-test-status">
              {searchTestResult.ok ? "● Online" : "○ Offline"}
            </span>
            {searchTestResult.provider && <span>{searchTestResult.provider}</span>}
            <span>{searchTestResult.latency_ms} ms</span>
            <span>{searchTestResult.result_count} результатов</span>
          </div>
          {searchTestResult.error && (
            <div className="search-test-error">{searchTestResult.error}</div>
          )}
          {searchTestResult.hint && (
            <div className="search-test-hint">{searchTestResult.hint}</div>
          )}
          {searchTestResult.results.slice(0, 3).map((item, index) => (
            <div className="search-test-hit" key={index}>
              <div className="search-test-hit-title">{item.title || "(без названия)"}</div>
              <div className="search-test-hit-url">{item.url}</div>
            </div>
          ))}
        </div>
      )}
      <GroupTitle>Доступ и разрешения</GroupTitle>
      <Row
        label="Файлы проекта"
        hint="Разрешить модели читать и редактировать файлы этой папки: list_files, read_file, write_file, edit_file"
      >
        <Toggle
          value={draft.workspace_tools_enabled}
          onChange={(v) => set("workspace_tools_enabled", v)}
        />
      </Row>
      <Row label="Режим разрешений" hint="plan · edit · auto · full (поверх ask/auto)">
        <select value={draft.autonomy_mode ?? "auto"} onChange={(e) => set("autonomy_mode", e.target.value as string)}>
          <option value="plan">Plan — только чтение</option>
          <option value="edit">Edit — правки в проекте, команды спрашивать</option>
          <option value="auto">Auto — безопасное само, рискованное спросить</option>
          <option value="full">Full — всё само, кроме опасного (осторожно)</option>
        </select>
      </Row>
      <Row label="Доступ AI" hint="read_only — только чтение · workspace — внутри проекта · full — весь ПК (осторожно)">
        <select value={draft.access_mode} onChange={(e) => set("access_mode", e.target.value as AxiomConfig["access_mode"])}>
          <option value="read_only">Только чтение</option>
          <option value="workspace">Проект (workspace)</option>
          <option value="full">Полный доступ</option>
        </select>
      </Row>
      <Row label="Терминал AI" hint="Разрешить модели выполнять команды в папке проекта">
        <Toggle value={draft.terminal_enabled} onChange={(v) => set("terminal_enabled", v)} />
      </Row>
      <GroupTitle>Лимиты веб-поиска</GroupTitle>
      <Row label="Источников на запрос" hint="Сколько результатов возвращает поиск">
        <input
          type="number"
          min={1}
          max={20}
          value={draft.search_max_sources}
          onChange={(e) => set("search_max_sources", Number(e.target.value))}
        />
      </Row>
      <Row label="Читать источники" hint="Сколько страниц загружать целиком для ответа">
        <input
          type="number"
          min={0}
          max={10}
          value={draft.search_read_sources}
          onChange={(e) => set("search_read_sources", Number(e.target.value))}
        />
      </Row>
      <Row label="Таймаут поиска, с" hint="Лимит ожидания поисковых провайдеров">
        <input
          type="number"
          min={1}
          max={120}
          value={draft.search_timeout}
          onChange={(e) => set("search_timeout", Number(e.target.value))}
        />
      </Row>
    </>
  );
}

const DENSITY_LABELS: Record<AxiomConfig["density"], string> = {
  compact: "Плотно",
  comfortable: "Обычно",
  spacious: "Просторно",
};

const ACCENT_LABELS: Record<AxiomConfig["accent"], string> = {
  garnet: "Гранатовый",
  blue: "Синий",
  teal: "Бирюзовый",
  violet: "Фиолетовый",
  slate: "Серый",
  rose: "Розовый",
  amber: "Янтарный",
};

function AppearanceSection({ draft, set }: SectionProps) {
  const [soundEnabled, setSoundEnabledState] = useState(isSoundEnabled);
  return (
    <>
      <GroupTitle>Цвет и оформление</GroupTitle>
      <Row label="Тема">
        <select
          value={draft.theme}
          onChange={(e) => set("theme", e.target.value as AxiomConfig["theme"])}
        >
          <option value="obsidian">AXIOM Dark</option>
          <option value="graphite">Graphite Grey</option>
          <option value="rosewood">Rose Noir</option>
          <option value="nord">Nord Frost</option>
          <option value="midnight">Midnight Blue</option>
          <option value="terminal">Terminal Green</option>
          <option value="solarized">Solarized Dark</option>
          <option value="light">AXIOM Light</option>
        </select>
      </Row>
      <Row label="Акцент" hint="Общий проверенный цвет для Desktop и TUI">
        <select
          value={draft.accent}
          onChange={(e) => set("accent", e.target.value as AxiomConfig["accent"])}
        >
          {(Object.keys(ACCENT_LABELS) as AxiomConfig["accent"][]).map((accent) => (
            <option key={accent} value={accent}>{ACCENT_LABELS[accent]}</option>
          ))}
        </select>
      </Row>
      <Row label="Подсветка панелей" hint="Выделять строки и кнопки панели при наведении">
        <Toggle value={draft.panel_hover} onChange={(v) => set("panel_hover", v)} />
      </Row>
      <GroupTitle>Движение и звук</GroupTitle>
      <Row label="Анимации" hint="Плавные переходы интерфейса">
        <Toggle value={draft.animations} onChange={(v) => set("animations", v)} />
      </Row>
      <Row label="Тихие UI-звуки" hint="Выключены по умолчанию. Применяется сразу, только в desktop UI. Без звука при вводе текста.">
        <Toggle
          value={soundEnabled}
          label="Тихие UI-звуки"
          onChange={(value) => {
            setSoundEnabledState(value);
            setSoundEnabled(value);
          }}
        />
      </Row>
      {/* Each event has its own cue; the only honest way to show that is to
          let the user hear them. Enabled only while sounds are on. */}
      <Row label="Проверить звуки" hint="Ответ готов, ошибка, запрос разрешения и остановка звучат по-разному.">
        <div className="sound-preview">
          {SOUND_PREVIEWS.map((preview) => (
            <button
              key={preview.kind}
              type="button"
              className="mini-btn"
              disabled={!soundEnabled}
              title={soundEnabled ? `Проиграть: ${preview.label}` : "Сначала включите UI-звуки"}
              onClick={() => playUiSound(preview.kind)}
            >
              {preview.label}
            </button>
          ))}
        </div>
      </Row>
      <GroupTitle>Плотность и панели</GroupTitle>
      <Row label="Плотность" hint="Отступы сообщений и списков">
        <select
          value={draft.density}
          onChange={(e) => set("density", e.target.value as AxiomConfig["density"])}
        >
          {(Object.keys(DENSITY_LABELS) as AxiomConfig["density"][]).map((d) => (
            <option key={d} value={d}>
              {DENSITY_LABELS[d]}
            </option>
          ))}
        </select>
      </Row>
      <Row label="Размер шрифта, px">
        <input
          type="number"
          min={11}
          max={20}
          value={draft.font_size}
          onChange={(e) => set("font_size", Number(e.target.value))}
        />
      </Row>
      <Row label="Боковая панель открыта">
        <Toggle value={draft.sidebar_open} onChange={(v) => set("sidebar_open", v)} />
      </Row>
      <Row label="Ширина панели, px">
        <input
          type="number"
          min={200}
          max={480}
          value={draft.sidebar_width}
          onChange={(e) => set("sidebar_width", Number(e.target.value))}
        />
      </Row>
    </>
  );
}

function AboutSection() {
  return (
    <div className="settings-about">
      <div className="about-brand">AXIOM</div>
      <div className="about-sub">LOCAL-FIRST AI WORKSPACE</div>
      <p className="about-text">
        AXIOM — агент для работы с проектом и документами. Он может отвечать в чате,
        искать по проекту, читать и изменять файлы, запускать команды и проверять результат.
        Один и тот же Python core используют TUI и desktop GUI.
      </p>
      <div className="about-grid">
        <div><b>Модели</b><span>Ollama и внешние API через единый streaming runtime.</span></div>
        <div><b>Проект</b><span>Файловые операции ограничены выбранной рабочей папкой.</span></div>
        <div><b>Инструменты</b><span>Чтение, поиск, редактирование, terminal, Git и web search.</span></div>
        <div><b>Контроль</b><span>Tool calls, timeline, permissions и stop reason видны в интерфейсе.</span></div>
      </div>
      <p className="about-text">
        API-ключи и история хранятся локально. Режим <b>auto_approve_all</b> разрешает
        инструменты без дополнительных вопросов — включайте его только для доверенного проекта.
      </p>
      <p className="about-text about-muted">
        Настройки: <code>~/.axiom/config.json</code> · история: <code>~/.axiom/history</code>.
        При старте выберите проект в верхней панели.
      </p>
    </div>
  );
}
function ShortcutsSection() {
  return (
    <div className="shortcuts-list">
      {SHORTCUTS.map((item) => (
        <div className="settings-row" key={item.label}>
          <div className="settings-row-text">
            <div className="settings-row-label">{item.label}</div>
          </div>
          <div className="settings-row-control">
            <span className="shortcut-keys">
              <kbd>{item.keys}</kbd>
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
