import { useState } from "react";
import { BookOpen, ChevronDown, ChevronRight, RefreshCw, Sparkles, Wrench } from "lucide-react";
import type { SkillRow } from "../../types";
import { useLocale } from "../../lib/locale";

const SOURCE_LABEL: Record<string, string> = {
  builtin: "ui.skills.source.builtin",
  global: "ui.skills.source.global",
  project: "ui.skills.source.project",
  plugin: "ui.skills.source.plugin",
};

function SkillCard({
  row,
  onToggle,
}: {
  row: SkillRow;
  onToggle: (id: string, pinned: boolean) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useLocale();
  return (
    <div className="skill-card">
      <div className="skill-head">
        <div className="skill-title">
          <BookOpen size={14} strokeWidth={1.8} />
          <span>{row.label}</span>
          <code className="skill-id">{row.id}</code>
          <span className="skill-badge">{t(SOURCE_LABEL[row.source] ?? row.source)}</span>
        </div>
        <button
          className={"switch" + (row.pinned ? " on" : "")}
          role="switch"
          aria-checked={row.pinned}
          aria-label={t("ui.skills.always_aria", { label: row.label })}
          onClick={() => void onToggle(row.id, row.pinned)}
        >
          <span className="switch-knob" />
        </button>
      </div>
      <div className="skill-tags">
        {row.triggers.length > 0 && (
          <span className="skill-tag">{t("ui.skills.triggers", { triggers: row.triggers.join(", ") })}</span>
        )}
        {row.tools.length > 0 && (
          <span className="skill-tag"><Wrench size={11} /> {row.tools.join(", ")}</span>
        )}
        <span className="skill-tag">{row.pinned ? t("ui.skills.always") : t("ui.skills.relevance")}</span>
      </div>
      {open && <div className="skill-instructions">{row.instructions}</div>}
      <button className="skill-expand" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />} {open ? t("ui.skills.hide") : t("ui.skills.show")}
      </button>
    </div>
  );
}

export default function SkillsPanel({
  rows,
  loading,
  onLoad,
  onToggle,
  onSuggest,
}: {
  rows: SkillRow[];
  loading: boolean;
  onLoad: () => Promise<void>;
  onToggle: (id: string, pinned: boolean) => Promise<void>;
  onSuggest: (text: string) => Promise<string[]>;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<string[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const { t } = useLocale();

  const suggest = async () => {
    if (!query.trim()) { setHits([]); return; }
    setSuggesting(true);
    setHits(await onSuggest(query));
    setSuggesting(false);
  };

  return (
    <div className="harness-panel">
      <div className="harness-toolbar">
        <p className="settings-row-hint">
          {t("ui.skills.hint")}
        </p>
        <button className="btn ghost" disabled={loading} onClick={() => void onLoad()}>
          <RefreshCw size={13} strokeWidth={1.8} />
          {loading ? t("ui.common.refreshing") : t("ui.common.refresh")}
        </button>
      </div>

      <div className="mcp-form">
        <input
          className="mcp-input grow"
          placeholder={t("ui.skills.placeholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void suggest(); }}
        />
        <button className="btn ghost" disabled={suggesting || !query.trim()} onClick={() => void suggest()}>
          <Sparkles size={13} /> {t("ui.skills.suggest")}
        </button>
      </div>

      {hits.length > 0 && (
        <div className="harness-result ok">
          <div className="harness-result-head"><Sparkles size={13} /> {t("ui.skills.matches")}</div>
          <div className="harness-result-body">{hits.join(", ")}</div>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="settings-empty">{t("ui.skills.none")}</div>
      ) : (
        <div className="skill-list">
          {rows.map((row) => <SkillCard key={row.id} row={row} onToggle={onToggle} />)}
        </div>
      )}
    </div>
  );
}
