import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import {
  ArrowLeft, BadgeCheck, BookOpen, Calculator, Clock, FileText, FolderOpen, Info, Loader2, NotebookPen,
  Package, Puzzle, Search, Shield, ShieldAlert, Trash2, Type, Wrench,
} from "lucide-react";
import type { PluginInstallResult, PluginRow } from "../../types";
import PluginPanelHost from "../PluginPanelHost";
import { useLocale } from "../../lib/locale";
import { plural } from "../../lib/i18n";
import calculatorCover from "../../assets/plugins/calculator.webp";
import datetimeCover from "../../assets/plugins/datetime.webp";
import notesCover from "../../assets/plugins/notes.webp";
import securityCover from "../../assets/plugins/security.webp";
import texttoolsCover from "../../assets/plugins/texttools.webp";

/* ------------------------------------------------------------ presentation */
const COVERS: Record<string, string> = {
  calculator: calculatorCover,
  datetime: datetimeCover,
  notes: notesCover,
  security: securityCover,
  texttools: texttoolsCover,
};

const META: Record<string, { title: string; category: string; icon: ReactNode }> = {
  calculator: { title: "ui.plugins.meta.calculator", category: "ui.plugins.category.utilities", icon: <Calculator size={18} /> },
  datetime: { title: "ui.plugins.meta.datetime", category: "ui.plugins.category.utilities", icon: <Clock size={18} /> },
  notes: { title: "ui.plugins.meta.notes", category: "ui.plugins.category.productivity", icon: <NotebookPen size={18} /> },
  security: { title: "ui.plugins.meta.security", category: "ui.plugins.category.security", icon: <Shield size={18} /> },
  texttools: { title: "ui.plugins.meta.texttools", category: "ui.plugins.category.text", icon: <Type size={18} /> },
};

const CAP_LABEL: Record<string, string> = {
  tools: "ui.plugins.cap.tools", skills: "ui.plugins.cap.skills", providers: "ui.plugins.cap.providers", ui: "ui.plugins.cap.ui", hooks: "ui.plugins.cap.hooks",
};

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

function metaOf(p: PluginRow) {
  const known = META[p.name];
  if (known) return known;
  const category = p.providers.length ? "ui.plugins.category.models" : p.skills.length ? "ui.plugins.category.skills" : p.tools.length ? "ui.plugins.category.tools" : "ui.plugins.category.extensions";
  const title = p.name.replace(/[-_]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  return { title, category, icon: <Puzzle size={18} /> };
}

function Cover({ plugin, large = false }: { plugin: PluginRow; large?: boolean }) {
  const src = COVERS[plugin.name];
  const meta = metaOf(plugin);
  if (src) return <div className={"pm-cover" + (large ? " large" : "")}><img src={src} alt="" loading="lazy" decoding="async" /></div>;
  const h = hash(plugin.name) % 360;
  return (
    <div className={"pm-cover pm-cover--gen" + (large ? " large" : "")}
      style={{ background: `radial-gradient(120% 90% at 80% 10%, hsl(${h} 70% 42% / .55), transparent 60%), radial-gradient(90% 80% at 10% 100%, hsl(${(h + 40) % 360} 70% 30% / .5), transparent 60%), #0b0b0e` }}>
      <span className="pm-cover-glyph">{meta.icon}</span>
    </div>
  );
}

type Filter = "all" | "installed" | "enabled" | "catalog";
type Tab = "overview" | "docs" | "permissions" | "details" | "panel";

interface Entry { plugin: PluginRow; installed: boolean }

/* ------------------------------------------------------------ main panel */
export default function PluginsMarketplace({
  rows, bundled, loading, onInstall, onInstallBundled, onToggle, onRequestTrust, onRequestRemove,
}: {
  rows: PluginRow[];
  bundled: PluginRow[];
  loading: boolean;
  onInstall: () => Promise<PluginInstallResult | null>;
  onInstallBundled: (name: string) => Promise<PluginInstallResult | null>;
  onToggle: (name: string, enabled: boolean) => Promise<PluginRow | null>;
  onRequestTrust: (plugin: PluginRow | null, action: "install" | "run", run: () => Promise<unknown>) => void;
  onRequestRemove: (plugin: PluginRow) => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [category, setCategory] = useState<string | null>(null);
  const [openName, setOpenName] = useState<string | null>(null);
  const { t, locale, strings } = useLocale();

  const entries = useMemo<Entry[]>(() => {
    const installed = new Set(rows.map((r) => r.name));
    return [
      ...rows.map((plugin) => ({ plugin, installed: true })),
      ...bundled.filter((b) => !installed.has(b.name)).map((plugin) => ({ plugin, installed: false })),
    ];
  }, [rows, bundled]);

  const categories = useMemo(() => [...new Set(entries.map((e) => metaOf(e.plugin).category))], [entries]);

  const visible = entries.filter(({ plugin, installed }) => {
    if (filter === "installed" && !installed) return false;
    if (filter === "enabled" && !(installed && plugin.enabled)) return false;
    if (filter === "catalog" && installed) return false;
    if (category && metaOf(plugin).category !== category) return false;
    const q = query.trim().toLowerCase();
    if (!q) return true;
    const m = metaOf(plugin);
    return [plugin.name, m.title, plugin.description, plugin.author, ...plugin.tools].join(" ").toLowerCase().includes(q);
  });

  const open = entries.find((e) => e.plugin.name === openName) ?? null;

  const install = (p: PluginRow) => onRequestTrust(p, "install", async () => onInstallBundled(p.name));
  const toggle = (p: PluginRow) => p.enabled
    ? void onToggle(p.name, false)
    : onRequestTrust(p, "run", async () => onToggle(p.name, true));

  if (open) {
    return <PluginDetail entry={open} loading={loading} onBack={() => setOpenName(null)} onInstall={install} onToggle={toggle} onRemove={onRequestRemove} />;
  }

  const counts: Record<Filter, number> = {
    all: entries.length,
    installed: rows.length,
    enabled: rows.filter((r) => r.enabled).length,
    catalog: entries.filter((e) => !e.installed).length,
  };

  return (
    <div className="pm">
      <div className="pm-hero">
        <div className="pm-hero-text">
          <h3>{t("ui.plugins.title")}</h3>
          <p>{t("ui.plugins.sub")}</p>
        </div>
        <button className="btn pm-hero-btn" disabled={loading} onClick={() => onRequestTrust(null, "install", onInstall)}>
          {loading ? <Loader2 size={14} className="spin" /> : <FolderOpen size={14} />} {t("ui.plugins.from_folder")}
        </button>
      </div>

      <div className="pm-toolbar">
        <label className="pm-search">
          <Search size={14} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("ui.plugins.search")} spellCheck={false} />
        </label>
        <div className="pm-filters" role="tablist">
          {(["all", "installed", "enabled", "catalog"] as Filter[]).map((f) => (
            <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>
              {{ all: t("ui.plugins.filter.all"), installed: t("ui.plugins.filter.installed"), enabled: t("ui.plugins.filter.enabled"), catalog: t("ui.plugins.filter.catalog") }[f]}
              <span>{counts[f]}</span>
            </button>
          ))}
        </div>
      </div>

      {categories.length > 1 && (
        <div className="pm-cats">
          <button className={!category ? "active" : ""} onClick={() => setCategory(null)}>{t("ui.plugins.all_categories")}</button>
          {categories.map((c) => <button key={c} className={category === c ? "active" : ""} onClick={() => setCategory(category === c ? null : c)}>{t(c)}</button>)}
        </div>
      )}

      {visible.length === 0 ? (
        <div className="pm-empty">
          <Package size={28} />
          <strong>{entries.length ? t("ui.plugins.not_found") : t("ui.plugins.none")}</strong>
          <span>{entries.length ? t("ui.plugins.not_found_hint") : t("ui.plugins.none_hint")}</span>
        </div>
      ) : (
        <div className="pm-grid">
          {visible.map(({ plugin, installed }) => {
            const m = metaOf(plugin);
            return (
              <article key={plugin.name} className="pm-card" tabIndex={0} onClick={() => setOpenName(plugin.name)}
                onKeyDown={(e) => { if (e.key === "Enter") setOpenName(plugin.name); }}>
                <div className="pm-card-media">
                  <Cover plugin={plugin} />
                  <span className="pm-cover-chip">{t(m.category)}</span>
                  {installed && <span className={"pm-cover-state" + (plugin.enabled ? " on" : "")}>{plugin.enabled ? t("ui.plugins.enabled") : t("ui.plugins.installed")}</span>}
                </div>
                <div className="pm-card-body">
                  <div className="pm-card-title">
                    <span className="pm-icon">{m.icon}</span>
                    <div>
                      <strong>{t(m.title)}</strong>
                      <span>{plugin.author || t("ui.plugins.unknown_author")}{plugin.bundled && <BadgeCheck size={12} className="pm-verified" />}</span>
                    </div>
                  </div>
                  <p className="pm-card-desc">{plugin.description || t("ui.plugins.custom")}</p>
                  <div className="pm-card-foot">
                    {plugin.tools.length > 0 && <span className="pm-tag" title={t("ui.plugins.tools")}><Wrench size={11} /> {plural("ui.plugins.tool", plugin.tools.length, locale, strings)}</span>}
                    <span className="pm-spacer" />
                    {installed ? (
                      <button
                        className={"switch" + (plugin.enabled ? " on" : "")}
                        role="switch"
                        aria-checked={plugin.enabled}
                        aria-label={`${plugin.enabled ? t("ui.plugins.disable") : t("ui.plugins.enable")} ${t(m.title)}`}
                        disabled={loading}
                        onClick={(e) => { e.stopPropagation(); toggle(plugin); }}
                      ><span className="switch-knob" /></button>
                    ) : (
                      <button className="btn primary small pm-get" disabled={loading} onClick={(e) => { e.stopPropagation(); install(plugin); }}>{t("ui.plugins.install")}</button>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <div className="plugin-security-note">
        {t("ui.plugins.security_note")}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ detail page */
function PluginDetail({ entry, loading, onBack, onInstall, onToggle, onRemove }: {
  entry: Entry;
  loading: boolean;
  onBack: () => void;
  onInstall: (p: PluginRow) => void;
  onToggle: (p: PluginRow) => void;
  onRemove: (p: PluginRow) => void;
}) {
  const { plugin, installed } = entry;
  const m = metaOf(plugin);
  const { t } = useLocale();
  const [tab, setTab] = useState<Tab>(plugin.readme ? "docs" : "overview");

  const panel = plugin.ui_block?.extensions.find((e) => e.type === "panel");

  const tabs: { id: Tab; label: string; icon: ReactNode }[] = [
    { id: "overview", label: t("ui.plugins.tab.overview"), icon: <Info size={13} /> },
    { id: "docs", label: t("ui.plugins.tab.docs"), icon: <BookOpen size={13} /> },
    ...(panel ? [{ id: "panel" as Tab, label: t("ui.plugins.tab.panel"), icon: <Puzzle size={13} /> }] : []),
    { id: "permissions", label: t("ui.plugins.tab.permissions"), icon: <ShieldAlert size={13} /> },
    { id: "details", label: t("ui.plugins.tab.details"), icon: <FileText size={13} /> },
  ];

  return (
    <div className="pm pm-detail">
      <button className="pm-back" onClick={onBack}><ArrowLeft size={14} /> {t("ui.plugins.back")}</button>

      <div className="pm-detail-hero">
        <Cover plugin={plugin} large />
        <div className="pm-detail-head">
          <span className="pm-icon pm-icon--lg">{m.icon}</span>
          <div className="pm-detail-title">
            <h3>{t(m.title)}</h3>
            <span>{plugin.author || t("ui.plugins.unknown_author")}{plugin.bundled && <> <BadgeCheck size={13} className="pm-verified" /> {t("ui.plugins.builtin")}</>} · v{plugin.version}</span>
          </div>
          <div className="pm-detail-actions">
            {installed ? (
              <>
                <button className={"btn " + (plugin.enabled ? "" : "primary")} disabled={loading} onClick={() => onToggle(plugin)}>
                  {plugin.enabled ? t("ui.plugins.disable") : t("ui.plugins.enable")}
                </button>
                <button className="btn danger ghost" disabled={loading} onClick={() => onRemove(plugin)} aria-label={t("ui.plugins.remove_aria", { name: plugin.name })}>
                  <Trash2 size={14} />
                </button>
              </>
            ) : (
              <button className="btn primary" disabled={loading} onClick={() => onInstall(plugin)}>{t("ui.plugins.install")}</button>
            )}
          </div>
        </div>
        <p className="pm-detail-desc">{plugin.description || t("ui.plugins.custom")}</p>
        <div className="pm-stats">
          <div><strong>{plugin.tools.length}</strong><span>{t("ui.plugins.tools_count")}</span></div>
          <div><strong>{plugin.skills.length}</strong><span>{t("ui.plugins.skills_count")}</span></div>
          <div><strong>{plugin.providers.length}</strong><span>{t("ui.plugins.providers_count")}</span></div>
          <div><strong className={installed ? (plugin.enabled ? "ok" : "") : ""}>{installed ? (plugin.enabled ? t("ui.plugins.on") : t("ui.plugins.off")) : "—"}</strong><span>{installed ? t("ui.plugins.status") : t("ui.plugins.not_installed")}</span></div>
        </div>
      </div>

      <div className="pm-tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.icon}{t.label}
          </button>
        ))}
      </div>

      <div className="pm-tab-body" key={tab}>
        {tab === "overview" && (
          <div className="pm-overview">
            {plugin.tools.length > 0 && (
              <section>
                <h4>{t("ui.plugins.tools_for_agent")}</h4>
                <div className="pm-tools">
                  {plugin.tools.map((t) => <div key={t} className="pm-tool"><Wrench size={13} /><code>{t}</code></div>)}
                </div>
              </section>
            )}
            {plugin.skills.length > 0 && (
              <section>
                <h4>{t("ui.plugins.skills_section")}</h4>
                <div className="pm-tools">{plugin.skills.map((t) => <div key={t} className="pm-tool"><BookOpen size={13} /><code>{t}</code></div>)}</div>
              </section>
            )}
            {plugin.providers.length > 0 && (
              <section>
                <h4>{t("ui.plugins.providers_section")}</h4>
                <div className="pm-tools">{plugin.providers.map((t) => <div key={t} className="pm-tool"><Package size={13} /><code>{t}</code></div>)}</div>
              </section>
            )}
            <section>
              <h4>{t("ui.plugins.how_to")}</h4>
              <ol className="pm-howto">
                <li>{installed ? t("ui.plugins.howto.1_installed") : t("ui.plugins.howto.1_install")}</li>
                <li>{t("ui.plugins.howto.2")}</li>
                <li>{t("ui.plugins.howto.3", { example: plugin.tools[0] ? t("ui.plugins.howto.3_example", { tool: plugin.tools[0] }) : "" })}</li>
              </ol>
            </section>
          </div>
        )}

        {tab === "docs" && (
          plugin.readme ? (
            <div className="pm-readme markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{plugin.readme}</ReactMarkdown>
            </div>
          ) : (
            <div className="pm-empty"><BookOpen size={24} /><strong>{t("ui.plugins.no_docs")}</strong><span>{t("ui.plugins.no_docs_hint")}</span></div>
          )
        )}

        {tab === "permissions" && (
          <div className="pm-perms">
            <div className="pm-perm-warn">
              <ShieldAlert size={16} />
              <div>
                <strong>{t("ui.plugins.perm_warn_title")}</strong>
                <span>{t("ui.plugins.perm_warn_body")}</span>
              </div>
            </div>
            <h4>{t("ui.plugins.manifest_caps")}</h4>
            <div className="pm-tools">
              {plugin.capabilities.length
                ? plugin.capabilities.map((c) => <div key={c} className="pm-tool"><Shield size={13} /><span>{t(CAP_LABEL[c] ?? c)}</span><code>{c}</code></div>)
                : <span className="pm-muted">{t("ui.plugins.not_declared")}</span>}
            </div>
            {plugin.ui_block?.scopes?.length ? (
              <>
                <h4>{t("ui.plugins.ui_scopes")}</h4>
                <div className="pm-tools">{plugin.ui_block.scopes.map((sc) => <div key={sc} className="pm-tool"><code>{sc}</code></div>)}</div>
              </>
            ) : null}
          </div>
        )}

        {tab === "details" && (
          <dl className="pm-dl">
            <dt>{t("ui.plugins.id")}</dt><dd><code>{plugin.name}</code></dd>
            <dt>{t("ui.plugins.version")}</dt><dd>{plugin.version}</dd>
            <dt>API</dt><dd>v{plugin.api_version}</dd>
            <dt>{t("ui.plugins.author")}</dt><dd>{plugin.author || "—"}</dd>
            <dt>{t("ui.plugins.source")}</dt><dd>{plugin.bundled ? t("ui.plugins.source.catalog") : t("ui.plugins.source.custom")}</dd>
            <dt>{t("ui.plugins.folder")}</dt><dd><code>{plugin.source_dir || "~/.axiom/plugins/" + plugin.name}</code></dd>
          </dl>
        )}

        {tab === "panel" && panel && <PluginPanelHost plugin={plugin} extension={panel} />}
      </div>
    </div>
  );
}
