import { useState, useEffect, useMemo, useRef, useId, createContext, useContext, isValidElement, cloneElement } from "react";
import {
  BookOpen,
  Check,
  Copy,
  Cpu,
  FolderOpen,
  HardDrive,
  Layers,
  Lock,
  Monitor,
  Puzzle,
  ShieldCheck,
  Terminal,
  Zap,
  Brain,
  Globe,
  Info,
  Keyboard,
  MessageSquare,
  RefreshCw,
  Search,
  Server,
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
  McpServerRow,
  SkillRow,
} from "../types";
import type { SettingsSection } from "../hooks/useAxiom";
import { isSoundEnabled, playUiSound, setSoundEnabled } from "../lib/sound";
import type { UiSound } from "../lib/sound";
import { localizedShortcutLabel } from "../lib/commands";
import { useLocale } from "../lib/locale";
import ProvidersPanel from "./settings/ProvidersPanel";
import PluginsMarketplace from "./settings/PluginsMarketplace";
import McpPanel from "./settings/McpPanel";
import SkillsPanel from "./settings/SkillsPanel";
import "../styles/settings.css";
import "../styles/settings-market.css";
import "../styles/settings-polish.css";
import "../styles/settings-harness.css";
import pkg from "../../package.json";

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
  // W3.5 MCP servers + Skills Manager.
  mcpRows: McpServerRow[];
  mcpLoading: boolean;
  onLoadMcp: () => Promise<void>;
  onAddMcp: (name: string, command: string[]) => Promise<McpServerRow | null>;
  onRemoveMcp: (name: string) => Promise<boolean>;
  onRestartMcp: (name: string) => Promise<McpServerRow | null>;
  onTestMcp: (name: string, tool?: string, argumentsJson?: string) => Promise<{ ok: boolean; content: string; error: string | null }>;
  skillRows: SkillRow[];
  skillLoading: boolean;
  onLoadSkills: () => Promise<void>;
  onToggleSkill: (id: string, pinned: boolean) => Promise<void>;
  onSuggestSkills: (text: string) => Promise<string[]>;
}

const SECTIONS: { key: SettingsSection; labelKey: string; icon: ReactNode }[] = [
  { key: "general", labelKey: "ui.settings.nav.general", icon: <Settings2 size={14} strokeWidth={1.8} /> },
  { key: "appearance", labelKey: "ui.settings.nav.appearance", icon: <Sparkles size={14} strokeWidth={1.8} /> },
  { key: "models", labelKey: "ui.settings.nav.models", icon: <SlidersHorizontal size={14} strokeWidth={1.8} /> },
  { key: "providers", labelKey: "ui.settings.nav.providers", icon: <Globe size={14} strokeWidth={1.8} /> },
  { key: "plugins", labelKey: "ui.settings.nav.plugins", icon: <Wrench size={14} strokeWidth={1.8} /> },
  { key: "mcp", labelKey: "ui.settings.nav.mcp", icon: <Server size={14} strokeWidth={1.8} /> },
  { key: "skills", labelKey: "ui.settings.nav.skills", icon: <Layers size={14} strokeWidth={1.8} /> },
  { key: "memory", labelKey: "ui.settings.nav.memory", icon: <Brain size={14} strokeWidth={1.8} /> },
  { key: "knowledge", labelKey: "ui.settings.nav.knowledge", icon: <BookOpen size={14} strokeWidth={1.8} /> },
  { key: "chat", labelKey: "ui.settings.nav.chat", icon: <MessageSquare size={14} strokeWidth={1.8} /> },
  { key: "tools", labelKey: "ui.settings.nav.tools", icon: <Wrench size={14} strokeWidth={1.8} /> },
  { key: "shortcuts", labelKey: "ui.settings.nav.shortcuts", icon: <Keyboard size={14} strokeWidth={1.8} /> },
  { key: "about", labelKey: "ui.settings.nav.about", icon: <Info size={14} strokeWidth={1.8} /> },
];

const SECTION_GROUPS: { labelKey: string; keys: SettingsSection[] }[] = [
  { labelKey: "ui.settings.group.workspace", keys: ["general", "appearance", "chat", "shortcuts"] },
  { labelKey: "ui.settings.group.ai", keys: ["models", "providers", "tools"] },
  { labelKey: "ui.settings.group.data", keys: ["memory", "knowledge"] },
  { labelKey: "ui.settings.group.ext", keys: ["plugins", "mcp", "skills"] },
  { labelKey: "ui.settings.group.system", keys: ["about"] },
];

/** Colour family of each group — drives the icon tiles in nav and header. */
const SECTION_TINT: Record<SettingsSection, string> = {
  general: "ws", appearance: "ws", chat: "ws", shortcuts: "ws",
  models: "ai", providers: "ai", tools: "ai",
  memory: "data", knowledge: "data",
  plugins: "ext", mcp: "ext", skills: "ext",
  about: "sys",
};

const SECTION_META: Record<SettingsSection, { eyebrowKey: string; titleKey: string; descriptionKey: string }> = {
  general: { eyebrowKey: "ui.settings.group.workspace", titleKey: "ui.settings.nav.general", descriptionKey: "ui.settings.desc.general" },
  appearance: { eyebrowKey: "ui.settings.group.workspace", titleKey: "ui.settings.nav.appearance", descriptionKey: "ui.settings.desc.appearance" },
  chat: { eyebrowKey: "ui.settings.group.workspace", titleKey: "ui.settings.nav.chat", descriptionKey: "ui.settings.desc.chat" },
  shortcuts: { eyebrowKey: "ui.settings.group.workspace", titleKey: "ui.settings.nav.shortcuts", descriptionKey: "ui.settings.desc.shortcuts" },
  models: { eyebrowKey: "ui.settings.group.ai", titleKey: "ui.settings.nav.models", descriptionKey: "ui.settings.desc.models" },
  providers: { eyebrowKey: "ui.settings.group.ai", titleKey: "ui.settings.nav.providers", descriptionKey: "ui.settings.desc.providers" },
  tools: { eyebrowKey: "ui.settings.group.ai", titleKey: "ui.settings.nav.tools", descriptionKey: "ui.settings.desc.tools" },
  memory: { eyebrowKey: "ui.settings.group.data", titleKey: "ui.settings.nav.memory", descriptionKey: "ui.settings.desc.memory" },
  knowledge: { eyebrowKey: "ui.settings.group.data", titleKey: "ui.settings.nav.knowledge", descriptionKey: "ui.settings.desc.knowledge" },
  plugins: { eyebrowKey: "ui.settings.group.ext", titleKey: "ui.settings.nav.plugins", descriptionKey: "ui.settings.desc.plugins" },
  mcp: { eyebrowKey: "ui.settings.group.ext", titleKey: "ui.settings.nav.mcp", descriptionKey: "ui.settings.desc.mcp" },
  skills: { eyebrowKey: "ui.settings.group.ext", titleKey: "ui.settings.nav.skills", descriptionKey: "ui.settings.desc.skills" },
  about: { eyebrowKey: "ui.settings.group.system", titleKey: "ui.settings.nav.about", descriptionKey: "ui.settings.desc.about" },
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
  const { t } = useLocale();
  const titleId = useId();
  return <div className="modal-backdrop settings-confirm-backdrop" onClick={(e) => { e.stopPropagation(); onClose(); }}>
    <div className="modal confirm settings-confirm" ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
      <div className="modal-head"><h2 id={titleId}>{title}</h2><button className="icon-btn" aria-label={t("ui.common.close")} onClick={onClose}><X size={16} /></button></div>
      {children}
    </div>
  </div>;
}

const SHORTCUTS: { keys: [string, string] | string; label: string; labelKey?: string }[] = [
  { keys: "Ctrl+N", label: "Новый разговор", labelKey: "ui.shortcut.new_conversation" },
  { keys: "Ctrl+B", label: "Показать/скрыть боковую панель", labelKey: "ui.shortcut.panel" },
  { keys: "Ctrl+K", label: "Поиск по разговорам", labelKey: "ui.shortcut.history_search_pl" },
  { keys: "Ctrl+F", label: "Поиск по текущему разговору", labelKey: "ui.shortcut.chat_search" },
  { keys: "Ctrl+,", label: "Настройки", labelKey: "ui.shortcut.settings" },
  { keys: "Ctrl+/", label: "Фокус в поле ввода", labelKey: "ui.shortcut.focus_input" },
  { keys: "Enter", label: "Отправить сообщение", labelKey: "ui.shortcut.send" },
  { keys: "Shift+Enter", label: "Перенос строки", labelKey: "ui.shortcut.newline" },
  { keys: "Ctrl+Enter", label: "Отправить с веб-поиском", labelKey: "ui.shortcut.send_web" },
  { keys: "Esc", label: "Остановить генерацию / закрыть окно", labelKey: "ui.shortcut.close" },
  { keys: "Ctrl+V", label: "Вставить изображение (vision-модели)", labelKey: "ui.shortcut.paste_image" },
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
  mcpRows,
  mcpLoading,
  onLoadMcp,
  onAddMcp,
  onRemoveMcp,
  onRestartMcp,
  onTestMcp,
  skillRows,
  skillLoading,
  onLoadSkills,
  onToggleSkill,
  onSuggestSkills,
}: Props) {
  const [draft, setDraft] = useState<AxiomConfig>(config);
  const { t } = useLocale();
  const dialogRef = useSettingsFocus(onClose);
  const contentRef = useRef<HTMLElement>(null);
  const meta = SECTION_META[section];
  const [navQuery, setNavQuery] = useState("");
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(config), [draft, config]);
  const sectionItem = SECTIONS.find((item) => item.key === section);
  const navGroups = useMemo(() => {
    const q = navQuery.trim().toLowerCase();
    if (!q) return SECTION_GROUPS;
    return SECTION_GROUPS
      .map((group) => ({
        ...group,
        keys: group.keys.filter((key) => {
          const item = SECTIONS.find((candidate) => candidate.key === key)!;
          const m = SECTION_META[key];
          return [t(item.labelKey), t(m.titleKey), t(m.descriptionKey), t(group.labelKey)].some((text) => text.toLowerCase().includes(q));
        }),
      }))
      .filter((group) => group.keys.length > 0);
  }, [navQuery, t]);
  const saveRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setDraft(config);
  }, [config]);

  useEffect(() => {
    if (section === "providers") void onLoadProviders();
    if (section === "plugins") void onLoadPlugins();
    if (section === "mcp") void onLoadMcp();
    if (section === "skills") void onLoadSkills();
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
      locale: draft.locale,
    };
    onSave(patch);
    onClose();
  };
  saveRef.current = save;

  return (
    <div className="modal-backdrop axiom-settings-backdrop" onClick={onClose}>
      <div className="modal axiom-settings" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="axiom-settings-title" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="axiom-settings-head">
          <h2 id="axiom-settings-title">
            <span className="settings-logo" aria-hidden="true"><span /></span>
            <span className="settings-wordmark">AXIOM</span>{t("ui.common.settings")}
          </h2>
          <button className="icon-btn" aria-label={t("ui.settings.close")} title={t("ui.settings.close_title")} onClick={onClose}>
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>

        <div className="axiom-settings-workspace">
          <nav className="settings-nav" aria-label={t("ui.settings.nav_aria")}>
            <label className="settings-nav-search">
              <Search size={13} strokeWidth={1.8} />
              <input
                value={navQuery}
                placeholder={t("ui.settings.search_placeholder")}
                aria-label={t("ui.settings.search_aria")}
                onChange={(e) => setNavQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && navGroups[0]?.keys[0]) { setSection(navGroups[0].keys[0]); }
                  if (e.key === "Escape" && navQuery) { e.stopPropagation(); setNavQuery(""); }
                }}
              />
            </label>
            {navGroups.length === 0 && <div className="settings-nav-empty">{t("ui.common.nothing_found")}</div>}
            {navGroups.map((group) => (
              <div className="settings-nav-group" key={group.labelKey}>
                <div className="settings-nav-group-label">{t(group.labelKey)}</div>
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
                      <span className={"settings-nav-icon tint-" + SECTION_TINT[item.key]}>{item.icon}</span>
                      <span>{t(item.labelKey)}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          <main className="settings-main" ref={contentRef} aria-labelledby="settings-section-heading" tabIndex={0}>
            <header className="settings-section-title">
              <span className={"settings-section-icon tint-" + SECTION_TINT[section]} aria-hidden="true">{sectionItem?.icon}</span>
              <div>
                <span className="settings-section-eyebrow">{t(meta.eyebrowKey)}</span>
                <h3 id="settings-section-heading">{t(meta.titleKey)}</h3>
                <p>{t(meta.descriptionKey)}</p>
              </div>
            </header>
            <div className="settings-content" key={section}>
            {section === "general" && <GeneralSection draft={draft} set={set} />}
            {section === "models" && <ModelsSection draft={draft} set={set} config={config} onRestartCore={onRestartCore} />}
            {section === "providers" && <ProvidersPanel rows={providerRows} models={providerModels} loading={providerLoading} activeModel={config.model} onSave={onProviderSaveSettings} onPickModel={onProviderPickModel} />}
            {section === "plugins" && <PluginsSection rows={pluginRows} bundled={bundledPlugins} loading={pluginLoading} onInstall={onInstallPlugin} onInstallBundled={onInstallBundledPlugin} onToggle={onTogglePlugin} onRemove={onRemovePlugin} />}
            {section === "mcp" && <McpPanel rows={mcpRows} loading={mcpLoading} onLoad={onLoadMcp} onAdd={onAddMcp} onRemove={onRemoveMcp} onRestart={onRestartMcp} onTest={onTestMcp} />}
            {section === "skills" && <SkillsPanel rows={skillRows} loading={skillLoading} onLoad={onLoadSkills} onToggle={onToggleSkill} onSuggest={onSuggestSkills} />}
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
            {section === "about" && <AboutSection config={config} pluginCount={pluginRows.length} providerCount={providerRows.length} />}
            </div>
          </main>
        </div>

        <div className="axiom-settings-foot">
          <button className="btn ghost settings-restart" onClick={onRestartCore}>
            <RefreshCw size={14} strokeWidth={1.8} />
            <span>{t("ui.settings.restart_core")}</span>
          </button>
          <span className={"settings-save-hint" + (dirty ? " dirty" : "")}>
            {dirty
              ? <><span className="settings-dirty-dot" />{t("ui.settings.save_hint.dirty")}</>
              : ["providers", "plugins", "mcp", "skills", "memory", "knowledge"].includes(section) ? t("ui.settings.save_hint.immediate") : t("ui.settings.save_hint.saved")}
          </span>
          <div className="modal-foot-spacer" />
          <button className="btn ghost" onClick={onClose}>
            {t("ui.common.cancel")}
          </button>
          <button className={"btn primary settings-save" + (dirty ? " pulse" : "")} onClick={save}>
            {t("ui.common.save")}
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
  const [pendingTrust, setPendingTrust] = useState<{ plugin: PluginRow | null; action: "install" | "run"; run: () => Promise<unknown> } | null>(null);
  const [pendingRemove, setPendingRemove] = useState<PluginRow | null>(null);
  const { t } = useLocale();

  const requestTrust = (plugin: PluginRow | null, action: "install" | "run", run: () => Promise<unknown>) => {
    setPendingTrust({ plugin, action, run });
  };

  const acceptTrust = async () => {
    const pending = pendingTrust;
    setPendingTrust(null);
    if (pending) await pending.run();
  };

  return (
    <div className="plugin-settings">
      <PluginsMarketplace
        rows={rows}
        bundled={bundled}
        loading={loading}
        onInstall={onInstall}
        onInstallBundled={onInstallBundled}
        onToggle={onToggle}
        onRequestTrust={requestTrust}
        onRequestRemove={setPendingRemove}
      />
      {pendingTrust && (
        <SettingsConfirmation title={t("ui.settings.plugins.trust_title")} onClose={() => setPendingTrust(null)}>
            <div className="modal-body">
              <strong>{pendingTrust.plugin ? `${pendingTrust.plugin.name} v${pendingTrust.plugin.version}` : t("ui.settings.plugins.from_folder")}</strong>
              {pendingTrust.plugin?.description && <p className="about-text">{pendingTrust.plugin.description}</p>}
              {pendingTrust.plugin?.tools.length ? <p className="about-text">{t("ui.settings.plugins.declared_tools", { tools: pendingTrust.plugin.tools.join(", ") })}</p> : null}
              {pendingTrust.plugin?.capabilities.length ? <p className="about-text">{t("ui.settings.plugins.capabilities", { caps: pendingTrust.plugin.capabilities.join(", ") })}</p> : null}
              {pendingTrust.plugin?.ui_block?.scopes?.length ? <p className="about-text">{t("ui.settings.plugins.ui_scopes", { scopes: pendingTrust.plugin.ui_block.scopes.join(", ") })}</p> : null}
              <p className="about-text">{t("ui.settings.plugins.import_warning")}</p>
              <p className="about-text">{pendingTrust.action === "run" ? t("ui.settings.plugins.run_confirm") : t("ui.settings.plugins.install_confirm")}</p>
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={() => setPendingTrust(null)}>{t("ui.common.cancel")}</button>
              <div className="modal-foot-spacer" />
              <button className="btn danger" onClick={() => void acceptTrust()}>{pendingTrust.action === "run" ? t("ui.settings.plugins.trust_run") : t("ui.settings.plugins.confirm_install")}</button>
            </div>
        </SettingsConfirmation>
      )}
      {pendingRemove && (
        <SettingsConfirmation title={t("ui.settings.plugins.remove_title")} onClose={() => setPendingRemove(null)}>
          <div className="modal-body"><strong>{pendingRemove.name}</strong><p className="about-text">{t("ui.settings.plugins.remove_body")}</p></div>
          <div className="modal-foot"><button className="btn ghost" onClick={() => setPendingRemove(null)}>{t("ui.common.cancel")}</button><div className="modal-foot-spacer" /><button className="btn danger" onClick={() => { const name = pendingRemove.name; setPendingRemove(null); void onRemove(name); }}>{t("ui.settings.plugins.remove_plugin")}</button></div>
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
  const { t } = useLocale();

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
          <h3>{t("ui.settings.memory.title")}</h3>
          <p>{t("ui.settings.memory.desc")}</p>
        </div>
        <button className="btn ghost" disabled={loading} onClick={() => void onLoad()}>
          <RefreshCw size={13} strokeWidth={1.8} />
          {loading ? t("ui.common.refreshing") : t("ui.common.refresh")}
        </button>
      </div>

      <div className="memory-form">
        <textarea
          className="memory-input"
          rows={2}
          placeholder={t("ui.settings.memory.placeholder")}
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <div className="memory-form-controls">
          <select className="memory-select" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="normal">{t("ui.settings.memory.cat.normal")}</option>
            <option value="sensitive">{t("ui.settings.memory.cat.sensitive")}</option>
          </select>
          <select className="memory-select" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="global">{t("ui.settings.memory.scope.global")}</option>
            <option value="project">{t("ui.settings.memory.scope.project")}</option>
          </select>
          <button className="btn primary" disabled={!content.trim()} onClick={() => void submit()}>
            {t("ui.settings.memory.remember")}
          </button>
        </div>
        <div className="settings-row-hint">
          {t("ui.settings.memory.banned_hint")}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="settings-empty">
          {t("ui.settings.memory.empty")}
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
                  <span className="memory-badge">{row.scope === "project" ? t("ui.settings.memory.badge.project") : t("ui.settings.memory.scope.global")}</span>
                  <span className="memory-badge">
                    {row.category === "sensitive" ? t("ui.settings.memory.badge.preference") : t("ui.settings.memory.badge.fact")}
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
                      {t("ui.common.save")}
                    </button>
                    <button className="btn ghost small" onClick={() => setEditing(null)}>
                      {t("ui.common.cancel")}
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn ghost small" onClick={() => startEdit(row)}>
                      {t("ui.common.edit")}
                    </button>
                    <button
                      className="btn danger small"
                      onClick={() => void onDelete(row.id)}
                      aria-label={t("ui.settings.memory.delete_aria", { content: row.content })}
                    >
                      {t("ui.common.delete")}
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
  const { t } = useLocale();

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
          <h3>{t("ui.settings.knowledge.title")}</h3>
          <p>{t("ui.settings.knowledge.desc")}</p>
        </div>
        <button className="btn ghost" disabled={loading} onClick={() => void onLoad()}>
          <RefreshCw size={13} strokeWidth={1.8} />
          {loading ? t("ui.common.refreshing") : t("ui.common.refresh")}
        </button>
      </div>

      <div className="memory-form">
        <div className="memory-form-controls">
          <input
            className="memory-input"
            placeholder={t("ui.settings.knowledge.name_placeholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="memory-input"
            placeholder={t("ui.settings.knowledge.path_placeholder")}
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <button className="btn primary" disabled={!path.trim() || loading} onClick={() => void submitAdd()}>
            {t("ui.settings.knowledge.index")}
          </button>
        </div>
        <div className="settings-row-hint">
          {t("ui.settings.knowledge.hint")}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="settings-empty">
          {t("ui.settings.knowledge.empty")}
        </div>
      ) : (
        <div className="memory-list">
          {rows.map((row) => (
            <div className="memory-card" key={row.name}>
              <div className="memory-card-main">
                <div className="memory-card-text">{row.name}</div>
                <div className="memory-card-meta">
                  <span className="memory-badge">{row.files} {t("ui.settings.knowledge.files")}</span>
                  <span className="memory-badge">{row.chunks} {t("ui.settings.knowledge.chunks")}</span>
                  <span className="memory-badge">{t("ui.settings.knowledge.embeddings", { v: row.embeddings })}</span>
                </div>
                <div className="settings-row-hint">{row.path}</div>
              </div>
              <div className="memory-card-actions">
                <button className="btn ghost small" disabled={loading} onClick={() => void onReindex(row.name)}>
                  {t("ui.settings.knowledge.reindex")}
                </button>
                <button className="btn danger small" onClick={() => void onRemove(row.name)}>
                  {t("ui.common.delete")}
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
            placeholder={t("ui.settings.knowledge.search_placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submitSearch(); }}
          />
          <button className="btn ghost" disabled={!query.trim() || rows.length === 0} onClick={() => void submitSearch()}>
            <Search size={13} strokeWidth={1.8} />
            {t("ui.common.search")}
          </button>
        </div>
      </div>
      {searched && hits.length === 0 && (
        <div className="settings-empty">{t("ui.settings.knowledge.no_hits")}</div>
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
const SOUND_PREVIEWS: { kind: UiSound; labelKey: string }[] = [
  { kind: "complete", labelKey: "ui.settings.sound.complete" },
  { kind: "error", labelKey: "ui.settings.sound.error" },
  { kind: "permission", labelKey: "ui.settings.sound.permission" },
  { kind: "stopped", labelKey: "ui.settings.sound.stopped" },
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
  const { t } = useLocale();
  return (
    <>
      <GroupTitle>{t("ui.settings.grp.language")}</GroupTitle>
      <Row label={t("ui.settings.language")} hint={t("ui.settings.language_hint")}>
        <select value={draft.locale} onChange={(e) => set("locale", e.target.value as AxiomConfig["locale"])}>
          <option value="ru">{t("ui.settings.lang.ru")}</option>
          <option value="en">{t("ui.settings.lang.en")}</option>
        </select>
      </Row>
      <GroupTitle>{t("ui.settings.grp.history")}</GroupTitle>
      <Row label={t("ui.settings.save_history")} hint={t("ui.settings.save_history_hint")}>
        <Toggle value={draft.save_history} onChange={(v) => set("save_history", v)} />
      </Row>
      <Row label={t("ui.settings.history_limit")} hint={t("ui.settings.history_limit_hint")}>
        <input
          type="number"
          min={0}
          max={500}
          value={draft.history_limit}
          onChange={(e) => set("history_limit", Number(e.target.value))}
        />
      </Row>
      <GroupTitle>{t("ui.settings.grp.behavior")}</GroupTitle>
      <Row label="Temperature" hint={t("ui.settings.temperature_hint")}>
        <input
          type="number"
          step={0.1}
          min={0}
          max={2}
          value={draft.temperature ?? ""}
          placeholder={t("ui.settings.auto_placeholder")}
          onChange={(e) => set("temperature", e.target.value === "" ? null : Number(e.target.value))}
        />
      </Row>
      <Row label={t("ui.settings.system_prompt")} hint={t("ui.settings.system_prompt_hint")}>
        <textarea
          rows={3}
          value={draft.system_prompt ?? ""}
          placeholder={t("ui.settings.default_placeholder")}
          onChange={(e) => set("system_prompt", e.target.value || null)}
        />
      </Row>
    </>
  );
}

function ModelsSection({ draft, set, config, onRestartCore }: SectionProps & { config: AxiomConfig; onRestartCore: () => void }) {
  const { t } = useLocale();
  return (
    <>
      <GroupTitle>{t("ui.settings.grp.ollama")}</GroupTitle>
      <Row label="Ollama URL" hint={t("ui.settings.ollama_url_hint", { url: config.ollama_url })}>
        <input
          value={draft.ollama_url}
          spellCheck={false}
          onChange={(e) => set("ollama_url", e.target.value)}
        />
      </Row>
      <GroupTitle>{t("ui.settings.grp.reasoning")}</GroupTitle>
      <Row label={t("ui.settings.think")} hint={t("ui.settings.think_hint")}>
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
          <option value="auto">{t("ui.settings.think.auto")}</option>
          <option value="on">{t("ui.settings.think.on")}</option>
          <option value="low">{t("ui.settings.think.low")}</option>
          <option value="medium">{t("ui.settings.think.medium")}</option>
          <option value="high">{t("ui.settings.think.high")}</option>
          <option value="max">{t("ui.settings.think.max")}</option>
        </select>
      </Row>
      <Row label={t("ui.settings.thinking_mode")} hint={t("ui.settings.thinking_mode_hint")}>
        <select
          value={draft.thinking_mode}
          onChange={(e) =>
            set("thinking_mode", e.target.value as AxiomConfig["thinking_mode"])
          }
        >
          <option value="auto">{t("ui.settings.thinking_mode.auto")}</option>
          <option value="fast">{t("ui.settings.thinking_mode.fast")}</option>
          <option value="normal">{t("ui.settings.thinking_mode.normal")}</option>
          <option value="deep">{t("ui.settings.thinking_mode.deep")}</option>
        </select>
      </Row>
      <GroupTitle>{t("ui.settings.grp.memory_limits")}</GroupTitle>
      <Row label={t("ui.settings.warmup")} hint={t("ui.settings.warmup_hint")}>
        <Toggle value={draft.warmup_model} onChange={(v) => set("warmup_model", v)} />
      </Row>
      <Row label={t("ui.settings.keep_alive")} hint={t("ui.settings.keep_alive_hint")}>
        <input
          value={draft.keep_alive}
          spellCheck={false}
          onChange={(e) => set("keep_alive", e.target.value)}
        />
      </Row>
      <Row label={t("ui.settings.num_ctx")} hint={t("ui.settings.num_ctx_hint")}>
        <input
          type="number"
          min={512}
          max={131072}
          step={512}
          value={draft.num_ctx ?? ""}
          placeholder={t("ui.settings.auto_placeholder")}
          onChange={(e) => set("num_ctx", e.target.value === "" ? null : Number(e.target.value))}
        />
      </Row>
      <Row label={t("ui.settings.num_predict")} hint={t("ui.settings.num_predict_hint")}>
        <input
          type="number"
          min={16}
          max={131072}
          value={draft.num_predict ?? ""}
          placeholder={t("ui.settings.auto_placeholder")}
          onChange={(e) =>
            set("num_predict", e.target.value === "" ? null : Number(e.target.value))
          }
        />
      </Row>
      <Row label={t("ui.settings.core")} hint={t("ui.settings.core_hint")}>
        <button className="btn ghost" onClick={onRestartCore}>
          {t("ui.settings.restart")}
        </button>
      </Row>
    </>
  );
}

function ChatSection({ draft, set }: SectionProps) {
  const { t } = useLocale();
  return (
    <>
      <GroupTitle>{t("ui.settings.grp.response")}</GroupTitle>
      <Row label="Markdown" hint={t("ui.settings.markdown_hint")}>
        <Toggle value={draft.render_markdown} onChange={(v) => set("render_markdown", v)} />
      </Row>
      <Row label={t("ui.settings.show_reasoning")} hint={t("ui.settings.show_reasoning_hint")}>
        <Toggle value={draft.show_reasoning} onChange={(v) => set("show_reasoning", v)} />
      </Row>
      <Row label={t("ui.settings.reasoning_expanded")} hint={t("ui.settings.reasoning_expanded_hint")}>
        <Toggle value={draft.reasoning_expanded} onChange={(v) => set("reasoning_expanded", v)} />
      </Row>
      <Row label={t("ui.settings.auto_scroll")} hint={t("ui.settings.auto_scroll_hint")}>
        <Toggle value={draft.auto_scroll} onChange={(v) => set("auto_scroll", v)} />
      </Row>
      <GroupTitle>{t("ui.settings.grp.context")}</GroupTitle>
      <Row label={t("ui.settings.show_metrics")} hint={t("ui.settings.show_metrics_hint")}>
        <Toggle value={draft.show_metrics} onChange={(v) => set("show_metrics", v)} />
      </Row>
      <Row label={t("ui.settings.show_context")} hint={t("ui.settings.show_context_hint")}>
        <Toggle value={draft.show_context} onChange={(v) => set("show_context", v)} />
      </Row>
      <Row label={t("ui.settings.context_messages")} hint={t("ui.settings.context_messages_hint")}>
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
  const { t } = useLocale();
  return (
    <>
      <GroupTitle>{t("ui.settings.grp.web")}</GroupTitle>
      <Row label={t("ui.settings.web_search")} hint={t("ui.settings.web_search_hint")}>
        <Toggle value={draft.web_search_enabled} onChange={(v) => set("web_search_enabled", v)} />
      </Row>
      <Row label={t("ui.settings.search_provider")} hint={t("ui.settings.search_provider_hint")}>
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
      <Row label={t("ui.settings.search_test")} hint={t("ui.settings.search_test_hint")}>
        <div className="search-test-control">
          <input
            value={testQuery}
            aria-label={t("ui.settings.search_query_aria")}
            spellCheck={false}
            placeholder={t("ui.settings.query_placeholder")}
            onChange={(e) => setTestQuery(e.target.value)}
          />
          <button
            className="btn ghost"
            disabled={searchTesting}
            onClick={() => void onRunSearchTest(testQuery)}
          >
            {searchTesting ? t("ui.settings.testing") : t("ui.settings.test")}
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
            <span>{searchTestResult.result_count} {t("ui.settings.results")}</span>
          </div>
          {searchTestResult.error && (
            <div className="search-test-error">{searchTestResult.error}</div>
          )}
          {searchTestResult.hint && (
            <div className="search-test-hint">{searchTestResult.hint}</div>
          )}
          {searchTestResult.results.slice(0, 3).map((item, index) => (
            <div className="search-test-hit" key={index}>
              <div className="search-test-hit-title">{item.title || t("ui.settings.untitled")}</div>
              <div className="search-test-hit-url">{item.url}</div>
            </div>
          ))}
        </div>
      )}
      <GroupTitle>{t("ui.settings.grp.access")}</GroupTitle>
      <Row
        label={t("ui.settings.project_files")}
        hint={t("ui.settings.project_files_hint")}
      >
        <Toggle
          value={draft.workspace_tools_enabled}
          onChange={(v) => set("workspace_tools_enabled", v)}
        />
      </Row>
      <Row label={t("ui.settings.permission_mode")} hint={t("ui.settings.permission_mode_hint")}>
        <select value={draft.autonomy_mode ?? "auto"} onChange={(e) => set("autonomy_mode", e.target.value as string)}>
          <option value="plan">{t("ui.settings.auto.plan")}</option>
          <option value="edit">{t("ui.settings.auto.edit")}</option>
          <option value="auto">{t("ui.settings.auto.auto")}</option>
          <option value="full">{t("ui.settings.auto.full")}</option>
        </select>
      </Row>
      <Row label={t("ui.settings.access_mode")} hint={t("ui.settings.access_mode_hint")}>
        <select value={draft.access_mode} onChange={(e) => set("access_mode", e.target.value as AxiomConfig["access_mode"])}>
          <option value="read_only">{t("ui.settings.access.read_only")}</option>
          <option value="workspace">{t("ui.settings.access.workspace")}</option>
          <option value="full">{t("ui.settings.access.full")}</option>
        </select>
      </Row>
      <Row label={t("ui.settings.terminal_ai")} hint={t("ui.settings.terminal_ai_hint")}>
        <Toggle value={draft.terminal_enabled} onChange={(v) => set("terminal_enabled", v)} />
      </Row>
      <GroupTitle>{t("ui.settings.grp.search_limits")}</GroupTitle>
      <Row label={t("ui.settings.sources")} hint={t("ui.settings.sources_hint")}>
        <input
          type="number"
          min={1}
          max={20}
          value={draft.search_max_sources}
          onChange={(e) => set("search_max_sources", Number(e.target.value))}
        />
      </Row>
      <Row label={t("ui.settings.read_sources")} hint={t("ui.settings.read_sources_hint")}>
        <input
          type="number"
          min={0}
          max={10}
          value={draft.search_read_sources}
          onChange={(e) => set("search_read_sources", Number(e.target.value))}
        />
      </Row>
      <Row label={t("ui.settings.search_timeout")} hint={t("ui.settings.search_timeout_hint")}>
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
  compact: "ui.settings.density.compact",
  comfortable: "ui.settings.density.comfortable",
  spacious: "ui.settings.density.spacious",
};

const ACCENT_LABELS: Record<AxiomConfig["accent"], string> = {
  garnet: "ui.settings.accent.garnet",
  blue: "ui.settings.accent.blue",
  teal: "ui.settings.accent.teal",
  violet: "ui.settings.accent.violet",
  slate: "ui.settings.accent.slate",
  rose: "ui.settings.accent.rose",
  amber: "ui.settings.accent.amber",
};

const ACCENT_COLORS: Record<AxiomConfig["accent"], string> = {
  garnet: "#ff5a4d", blue: "#58A6FF", teal: "#2DD4BF", violet: "#A78BFA", slate: "#C3C8CF", rose: "#F2789F", amber: "#F0A93C",
};
/** Themes whose accent follows the user's choice (others ship a fixed one). */
const ACCENT_THEMES: AxiomConfig["theme"][] = ["obsidian", "graphite", "light"];
const THEME_PREVIEWS: { id: AxiomConfig["theme"]; name: string; bg: string; panel: string; elevated: string; text: string; accent: string }[] = [
  { id: "obsidian", name: "AXIOM Dark", bg: "#050506", panel: "#0a0a0c", elevated: "#121216", text: "#ececf0", accent: "#ff5a4d" },
  { id: "graphite", name: "Graphite Grey", bg: "#17181A", panel: "#1C1E21", elevated: "#23262A", text: "#E8E9EA", accent: "#C3C8CF" },
  { id: "rosewood", name: "Rose Noir", bg: "#0B0709", panel: "#120C0F", elevated: "#1A1216", text: "#F5EAEE", accent: "#F2789F" },
  { id: "nord", name: "Nord Frost", bg: "#2E3440", panel: "#333A48", elevated: "#3B4252", text: "#ECEFF4", accent: "#88C0D0" },
  { id: "midnight", name: "Midnight Blue", bg: "#0D1117", panel: "#111820", elevated: "#1B2632", text: "#F0F6FC", accent: "#58A6FF" },
  { id: "terminal", name: "Terminal Green", bg: "#000000", panel: "#050505", elevated: "#101010", text: "#F2FFF4", accent: "#00FF41" },
  { id: "solarized", name: "Solarized Dark", bg: "#002B36", panel: "#073642", elevated: "#104B56", text: "#FDF6E3", accent: "#B58900" },
  { id: "light", name: "AXIOM Light", bg: "#FFF7F7", panel: "#FFF0F0", elevated: "#FFFFFF", text: "#171717", accent: "#E0352A" },
];
function accentFor(theme: AxiomConfig["theme"], accent: AxiomConfig["accent"]): string {
  if (ACCENT_THEMES.includes(theme)) return ACCENT_COLORS[accent];
  return THEME_PREVIEWS.find((t) => t.id === theme)?.accent ?? ACCENT_COLORS.garnet;
}

function AppearanceSection({ draft, set }: SectionProps) {
  const [soundEnabled, setSoundEnabledState] = useState(isSoundEnabled);
  const { t } = useLocale();
  return (
    <>
      <GroupTitle>{t("ui.settings.grp.color")}</GroupTitle>
      <div className="theme-picker" role="radiogroup" aria-label={t("ui.settings.theme_aria")}>
        {THEME_PREVIEWS.map((theme) => (
          <button
            key={theme.id}
            type="button"
            role="radio"
            aria-checked={draft.theme === theme.id}
            className={"theme-card" + (draft.theme === theme.id ? " active" : "")}
            onClick={() => set("theme", theme.id)}
          >
            <span className="theme-preview" style={{ background: theme.bg }}>
              <span className="theme-preview-side" style={{ background: theme.panel }} />
              <span className="theme-preview-main">
                <span style={{ background: theme.text, width: "62%" }} />
                <span style={{ background: theme.text, width: "44%", opacity: 0.45 }} />
                <span className="theme-preview-bubble" style={{ background: theme.elevated }} />
                <span className="theme-preview-accent" style={{ background: accentFor(theme.id, draft.accent) }} />
              </span>
            </span>
            <span className="theme-card-label">
              {theme.name}
              {draft.theme === theme.id && <Check size={12} strokeWidth={2.4} />}
            </span>
          </button>
        ))}
      </div>
      <Row label={t("ui.settings.accent")} hint={ACCENT_THEMES.includes(draft.theme) ? t("ui.settings.accent_hint_shared") : t("ui.settings.accent_hint_own")}>
        <div className="accent-picker" role="radiogroup" aria-label={t("ui.settings.accent_aria")}>
          {(Object.keys(ACCENT_LABELS) as AxiomConfig["accent"][]).map((accent) => (
            <button
              key={accent}
              type="button"
              role="radio"
              aria-checked={draft.accent === accent}
              title={t(ACCENT_LABELS[accent])}
              aria-label={t(ACCENT_LABELS[accent])}
              className={"accent-dot" + (draft.accent === accent ? " active" : "")}
              style={{ ["--dot" as string]: ACCENT_COLORS[accent] }}
              onClick={() => set("accent", accent)}
            >
              {draft.accent === accent && <Check size={11} strokeWidth={3} />}
            </button>
          ))}
          <span className="accent-name">{t(ACCENT_LABELS[draft.accent])}</span>
        </div>
      </Row>
      <Row label={t("ui.settings.panel_hover")} hint={t("ui.settings.panel_hover_hint")}>
        <Toggle value={draft.panel_hover} onChange={(v) => set("panel_hover", v)} />
      </Row>
      <GroupTitle>{t("ui.settings.grp.motion")}</GroupTitle>
      <Row label={t("ui.settings.animations")} hint={t("ui.settings.animations_hint")}>
        <Toggle value={draft.animations} onChange={(v) => set("animations", v)} />
      </Row>
      <Row label={t("ui.settings.ui_sounds")} hint={t("ui.settings.ui_sounds_hint")}>
        <Toggle
          value={soundEnabled}
          label={t("ui.settings.ui_sounds")}
          onChange={(value) => {
            setSoundEnabledState(value);
            setSoundEnabled(value);
          }}
        />
      </Row>
      <Row label={t("ui.settings.test_sounds")} hint={t("ui.settings.test_sounds_hint")}>
        <div className="sound-preview">
          {SOUND_PREVIEWS.map((preview) => (
            <button
              key={preview.kind}
              type="button"
              className="mini-btn"
              disabled={!soundEnabled}
              title={soundEnabled ? t("ui.settings.play", { label: t(preview.labelKey) }) : t("ui.settings.enable_sounds")}
              onClick={() => playUiSound(preview.kind)}
            >
              {t(preview.labelKey)}
            </button>
          ))}
        </div>
      </Row>
      <GroupTitle>{t("ui.settings.grp.density")}</GroupTitle>
      <Row label={t("ui.settings.density")} hint={t("ui.settings.density_hint")}>
        <select
          value={draft.density}
          onChange={(e) => set("density", e.target.value as AxiomConfig["density"])}
        >
          {(Object.keys(DENSITY_LABELS) as AxiomConfig["density"][]).map((d) => (
            <option key={d} value={d}>
              {t(DENSITY_LABELS[d])}
            </option>
          ))}
        </select>
      </Row>
      <Row label={t("ui.settings.font_size")}>
        <input
          type="number"
          min={11}
          max={20}
          value={draft.font_size}
          onChange={(e) => set("font_size", Number(e.target.value))}
        />
      </Row>
      <Row label={t("ui.settings.sidebar_open")}>
        <Toggle value={draft.sidebar_open} onChange={(v) => set("sidebar_open", v)} />
      </Row>
      <Row label={t("ui.settings.sidebar_width")}>
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

const ACCESS_LABELS: Record<string, string> = { read_only: "ui.settings.access.read_only", workspace: "ui.settings.access.workspace", full: "ui.settings.access.full" };

function AboutSection({ config, pluginCount, providerCount }: { config: AxiomConfig; pluginCount: number; providerCount: number }) {
  const { t } = useLocale();
  const [copied, setCopied] = useState<string | null>(null);
  const platform = typeof navigator !== "undefined" ? (/Windows/i.test(navigator.userAgent) ? "Windows" : /Mac/i.test(navigator.userAgent) ? "macOS" : "Linux") : "—";
  const facts: { icon: ReactNode; label: string; value: string; mono?: boolean }[] = [
    { icon: <Cpu size={14} />, label: t("ui.settings.about.active_model"), value: config.model || t("ui.settings.about.not_selected"), mono: true },
    { icon: <Zap size={14} />, label: "Ollama", value: config.ollama_url || "—", mono: true },
    { icon: <FolderOpen size={14} />, label: t("ui.settings.about.project"), value: config.workspace_root || t("ui.settings.about.not_chosen"), mono: true },
    { icon: <Lock size={14} />, label: t("ui.settings.about.ai_access"), value: t(ACCESS_LABELS[config.access_mode] ?? config.access_mode) },
    { icon: <Globe size={14} />, label: t("ui.settings.about.providers"), value: String(providerCount) },
    { icon: <Puzzle size={14} />, label: t("ui.settings.about.plugins"), value: String(pluginCount) },
  ];
  const paths = [
    { label: t("ui.common.settings"), value: "~/.axiom/config.json" },
    { label: t("ui.settings.about.history"), value: "~/.axiom/history" },
    { label: t("ui.settings.about.plugins"), value: "~/.axiom/plugins" },
  ];
  const copy = async (key: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(key); window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 1400); } catch { /* clipboard blocked */ }
  };
  const diagnostics = [
    `AXIOM ${pkg.version} · desktop (Tauri 2 + React 18) · ${platform}`,
    ...facts.map((f) => `${f.label}: ${f.value}`),
  ].join("\n");

  return (
    <div className="about-v2">
      <section className="about-hero">
        <div className="about-orbit" aria-hidden="true">
          <span className="about-ring r1" /><span className="about-ring r2" /><span className="about-ring r3" />
          <span className="about-core" />
          <span className="about-planet" />
        </div>
        <div className="about-hero-text">
          <div className="about-wordmark">AXIOM</div>
          <p className="about-tagline">{t("ui.settings.about.tagline")}</p>
          <div className="about-chips">
            <span className="about-chip accent">v{pkg.version}</span>
            <span className="about-chip">Desktop · Tauri 2</span>
            <span className="about-chip">TUI · Textual</span>
            <span className="about-chip">{platform}</span>
            <span className="about-chip">MIT License</span>
          </div>
        </div>
        <button className="btn ghost about-copy" onClick={() => void copy("diag", diagnostics)}>
          {copied === "diag" ? <Check size={13} /> : <Copy size={13} />}
          {copied === "diag" ? t("ui.settings.about.copied") : t("ui.settings.about.copy_details")}
        </button>
      </section>

      <h4 className="about-h">{t("ui.settings.about.current_config")}</h4>
      <div className="about-facts">
        {facts.map((fact) => (
          <div className="about-fact" key={fact.label}>
            <span className="about-fact-icon">{fact.icon}</span>
            <span className="about-fact-label">{fact.label}</span>
            <span className={"about-fact-value" + (fact.mono ? " mono" : "")} title={fact.value}>{fact.value}</span>
          </div>
        ))}
      </div>

      <h4 className="about-h">{t("ui.settings.about.what")}</h4>
      <div className="about-features">
        {[
          { icon: <MessageSquare size={16} />, title: t("ui.settings.about.feature.chat.title"), text: t("ui.settings.about.feature.chat.text") },
          { icon: <FolderOpen size={16} />, title: t("ui.settings.about.feature.project.title"), text: t("ui.settings.about.feature.project.text") },
          { icon: <Terminal size={16} />, title: t("ui.settings.about.feature.terminal.title"), text: t("ui.settings.about.feature.terminal.text") },
          { icon: <Layers size={16} />, title: t("ui.settings.about.feature.agents.title"), text: t("ui.settings.about.feature.agents.text") },
          { icon: <Puzzle size={16} />, title: t("ui.settings.about.feature.plugins.title"), text: t("ui.settings.about.feature.plugins.text") },
          { icon: <ShieldCheck size={16} />, title: t("ui.settings.about.feature.control.title"), text: t("ui.settings.about.feature.control.text") },
        ].map((feature) => (
          <div className="about-feature" key={feature.title}>
            <span className="about-feature-icon">{feature.icon}</span>
            <b>{feature.title}</b>
            <span>{feature.text}</span>
          </div>
        ))}
      </div>

      <h4 className="about-h">{t("ui.settings.about.architecture")}</h4>
      <div className="about-arch" aria-label={t("ui.settings.about.arch.scheme")}>
        <div className="about-arch-col">
          <div className="about-node"><Monitor size={14} /><b>Desktop GUI</b><span>Tauri 2 · React 18</span></div>
          <div className="about-node"><Terminal size={14} /><b>TUI</b><span>Textual</span></div>
        </div>
        <div className="about-arch-link" aria-hidden="true"><span /></div>
        <div className="about-node core"><Cpu size={14} /><b>Python core</b><span>ChatSession · tools · permissions</span></div>
        <div className="about-arch-link" aria-hidden="true"><span /></div>
        <div className="about-arch-col">
          <div className="about-node"><Zap size={14} /><b>Ollama</b><span>{t("ui.settings.about.local_models")}</span></div>
          <div className="about-node"><Globe size={14} /><b>API-провайдеры</b><span>{t("ui.settings.about.cloud_models")}</span></div>
          <div className="about-node"><HardDrive size={14} /><b>{t("ui.settings.about.project")}</b><span>{t("ui.settings.about.project_desc")}</span></div>
        </div>
      </div>

      <h4 className="about-h">{t("ui.settings.about.privacy")}</h4>
      <div className="about-privacy">
        <div><Lock size={14} /><span>{t("ui.settings.about.privacy.local")}</span></div>
        <div><ShieldCheck size={14} /><span>{t("ui.settings.about.privacy.auto")}</span></div>
        <div><Puzzle size={14} /><span>{t("ui.settings.about.privacy.plugins")}</span></div>
      </div>

      <h4 className="about-h">{t("ui.settings.about.data_where")}</h4>
      <div className="about-paths">
        {paths.map((item) => (
          <div className="about-path" key={item.label}>
            <span>{item.label}</span>
            <code>{item.value}</code>
            <button className="icon-btn" aria-label={`${t("ui.settings.about.copy_details")}: ${item.label}`} onClick={() => void copy(item.label, item.value)}>
              {copied === item.label ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
        ))}
      </div>

      <p className="about-foot">{t("ui.settings.about.foot")}</p>
    </div>
  );
}
function ShortcutsSection() {
  // W3.8: shortcut captions follow the core RU/EN catalog.
  const { t } = useLocale();
  return (
    <div className="shortcuts-list">
      {SHORTCUTS.map((item) => (
        <div className="settings-row" key={Array.isArray(item.keys) ? item.keys.join("+") : item.keys}>
          <div className="settings-row-text">
            <div className="settings-row-label">{localizedShortcutLabel(item, t)}</div>
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
