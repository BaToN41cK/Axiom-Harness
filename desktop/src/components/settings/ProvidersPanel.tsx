import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, ExternalLink, Eye, EyeOff, KeyRound, Loader2, Search, Server, Sparkles, Zap } from "lucide-react";
import type { ProviderModelRow, ProviderRow } from "../../types";
import { openExternal } from "../../bridge";

/** Where to get an API key for each well-known provider. */
const KEY_PAGES: Record<string, string> = {
  anthropic: "https://console.anthropic.com/settings/keys",
  openai: "https://platform.openai.com/api-keys",
  gemini: "https://aistudio.google.com/app/apikey",
  deepseek: "https://platform.deepseek.com/api_keys",
  xai: "https://console.x.ai",
  mistral: "https://console.mistral.ai/api-keys",
  qwen: "https://dashscope.console.aliyun.com/apiKey",
  zai: "https://z.ai/manage-apikey/apikey-list",
  openrouter: "https://openrouter.ai/keys",
  together: "https://api.together.xyz/settings/api-keys",
  fireworks: "https://fireworks.ai/account/api-keys",
  groq: "https://console.groq.com/keys",
  cerebras: "https://cloud.cerebras.ai",
};

const BRAND: Record<string, { bg: string; fg: string; mono: string; tagline: string }> = {
  anthropic: { bg: "#d97757", fg: "#1a0f0a", mono: "A", tagline: "Claude — сильный в коде и рассуждениях" },
  openai: { bg: "#10a37f", fg: "#fff", mono: "O", tagline: "GPT — универсальные модели" },
  openai_compatible: { bg: "#3a3a44", fg: "#fff", mono: "{}", tagline: "Любой сервер с OpenAI API (/v1)" },
  gemini: { bg: "#4b7bec", fg: "#fff", mono: "G", tagline: "Gemini — длинный контекст" },
  deepseek: { bg: "#4d6bfe", fg: "#fff", mono: "D", tagline: "DeepSeek — недорогие сильные модели" },
  xai: { bg: "#111", fg: "#fff", mono: "X", tagline: "Grok — быстрые модели для кода" },
  mistral: { bg: "#fa520f", fg: "#fff", mono: "M", tagline: "Mistral и Codestral" },
  qwen: { bg: "#615ced", fg: "#fff", mono: "Q", tagline: "Qwen — открытые модели Alibaba" },
  zai: { bg: "#2d2d2d", fg: "#fff", mono: "Z", tagline: "GLM — модели Zhipu" },
  openrouter: { bg: "#6467f2", fg: "#fff", mono: "R", tagline: "Сотни моделей через один ключ" },
  together: { bg: "#0f6fff", fg: "#fff", mono: "T", tagline: "Открытые модели в облаке" },
  fireworks: { bg: "#6720ff", fg: "#fff", mono: "F", tagline: "Быстрый инференс открытых моделей" },
  groq: { bg: "#f55036", fg: "#fff", mono: "Gq", tagline: "Сверхбыстрый инференс на LPU" },
  cerebras: { bg: "#f05a28", fg: "#fff", mono: "C", tagline: "Самый быстрый инференс" },
  ollama: { bg: "#f2f2f2", fg: "#111", mono: "◉", tagline: "Локальные модели на этом компьютере" },
};

const brandOf = (id: string, label: string) =>
  BRAND[id] ?? { bg: "#2a2a32", fg: "#fff", mono: (label[0] || "?").toUpperCase(), tagline: "Провайдер моделей" };

function ProviderLogo({ id, label, size = 30 }: { id: string; label: string; size?: number }) {
  const b = brandOf(id, label);
  return (
    <span className="prov-logo" style={{ width: size, height: size, background: b.bg, color: b.fg, fontSize: size * (b.mono.length > 1 ? 0.36 : 0.46) }}>
      {b.mono}
    </span>
  );
}

const isLocal = (row: ProviderRow) => row.id === "ollama" || /127\.0\.0\.1|localhost/.test(row.base_url);

function statusOf(row: ProviderRow): { tone: "ok" | "warn" | "idle"; text: string } {
  if (row.configured) return { tone: "ok", text: "Подключён" };
  if (isLocal(row)) return { tone: "idle", text: "Локальный" };
  return { tone: "warn", text: "Нужен ключ" };
}

function fmtContext(n: number | null): string | null {
  if (!n) return null;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}K`;
  return String(n);
}

const CAP_LABEL: Record<string, string> = {
  tools: "инструменты", vision: "изображения", reasoning: "рассуждения", streaming: "стриминг", chat: "чат", code: "код", json: "JSON",
};

export default function ProvidersPanel({ rows, models, loading, activeModel, onSave, onPickModel }: {
  rows: ProviderRow[];
  models: ProviderModelRow[];
  loading: boolean;
  activeModel: string | null;
  onSave: (id: string, key: string, baseUrl: string) => Promise<void>;
  onPickModel: (providerId: string, model: string) => Promise<void>;
}) {
  const sorted = useMemo(
    () => [...rows].sort((a, b) => Number(b.configured) - Number(a.configured)),
    [rows],
  );
  const [selected, setSelected] = useState<string>(() => sorted.find((r) => r.configured)?.id ?? sorted[0]?.id ?? "openai_compatible");
  const [filter, setFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [picking, setPicking] = useState<string | null>(null);

  useEffect(() => {
    if (sorted.length && !sorted.some((r) => r.id === selected)) setSelected(sorted.find((r) => r.configured)?.id ?? sorted[0].id);
  }, [sorted, selected]);

  const row = sorted.find((r) => r.id === selected) ?? sorted[0];
  useEffect(() => {
    setBaseUrl(row?.base_url || "");
    setKey("");
    setShowKey(false);
    setModelFilter("");
    setAdvanced(row?.id === "openai_compatible" || !row?.base_url);
  }, [row?.id, row?.base_url]);

  const visible = sorted.filter((r) => !filter.trim() || (r.label + " " + r.id).toLowerCase().includes(filter.trim().toLowerCase()));
  const providerModels = models
    .filter((m) => m.provider_id === row?.id)
    .filter((m) => !modelFilter.trim() || (m.label + " " + m.model).toLowerCase().includes(modelFilter.trim().toLowerCase()));
  const connectedCount = rows.filter((r) => r.configured).length;

  if (!row) {
    return <div className="settings-empty">{loading ? "Загрузка провайдеров…" : "Провайдеры не найдены."}</div>;
  }

  const brand = brandOf(row.id, row.label);
  const status = statusOf(row);
  const keyPage = KEY_PAGES[row.id];
  const needsKey = !isLocal(row);
  const needsUrl = row.id === "openai_compatible" || !row.base_url;
  const canConnect = !loading && (!needsUrl || baseUrl.trim().length > 0);

  const pick = async (model: string) => {
    setPicking(model);
    try { await onPickModel(row.id, model); } finally { setPicking(null); }
  };

  return (
    <div className="prov">
      {/* ---------------------------------------------------- active model */}
      <div className="prov-active">
        <span className="prov-active-icon"><Sparkles size={15} /></span>
        <div className="prov-active-text">
          <span>Активная модель</span>
          <strong>{activeModel || "не выбрана — используется модель по умолчанию"}</strong>
        </div>
        <span className="prov-active-count">{connectedCount} из {rows.length} подключено</span>
      </div>

      <div className="prov-layout">
        {/* -------------------------------------------------- provider list */}
        <aside className="prov-list">
          <label className="prov-search">
            <Search size={13} />
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Найти провайдера" spellCheck={false} />
          </label>
          <div className="prov-list-scroll" role="listbox" aria-label="Провайдеры">
            {visible.map((r) => {
              const st = statusOf(r);
              return (
                <button key={r.id} role="option" aria-selected={r.id === row.id} className={"prov-item" + (r.id === row.id ? " active" : "")} onClick={() => setSelected(r.id)}>
                  <ProviderLogo id={r.id} label={r.label} size={26} />
                  <span className="prov-item-text">
                    <strong>{r.label}</strong>
                    <span className={"prov-dot " + st.tone}>{st.text}</span>
                  </span>
                </button>
              );
            })}
            {!visible.length && <div className="prov-list-empty">Ничего не найдено</div>}
          </div>
        </aside>

        {/* -------------------------------------------------- detail */}
        <section className="prov-detail" key={row.id}>
          <header className="prov-head">
            <ProviderLogo id={row.id} label={row.label} size={44} />
            <div className="prov-head-text">
              <h3>{row.label}</h3>
              <p>{brand.tagline}</p>
            </div>
            <span className={"prov-badge " + status.tone}>{status.tone === "ok" && <Check size={12} strokeWidth={3} />}{status.text}</span>
          </header>

          {/* step 1 — connection */}
          <div className="prov-step">
            <div className="prov-step-head">
              <span className={"prov-step-num" + (row.configured ? " done" : "")}>{row.configured ? <Check size={12} strokeWidth={3} /> : 1}</span>
              <strong>Подключение</strong>
              {keyPage && (
                <button className="prov-link" onClick={() => void openExternal(keyPage)}>
                  Получить ключ <ExternalLink size={12} />
                </button>
              )}
            </div>

            {needsKey && (
              <label className="prov-field">
                <span>API-ключ</span>
                <span className="prov-input">
                  <KeyRound size={14} />
                  <input
                    type={showKey ? "text" : "password"}
                    value={key}
                    spellCheck={false}
                    autoComplete="off"
                    placeholder={row.configured ? "•••••••••••• сохранён — оставьте пустым" : "Вставьте ключ, например sk-…"}
                    onChange={(e) => setKey(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && canConnect) void onSave(row.id, key, baseUrl.trim()); }}
                  />
                  <button type="button" className="prov-eye" onClick={() => setShowKey(!showKey)} aria-label={showKey ? "Скрыть ключ" : "Показать ключ"}>
                    {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </span>
              </label>
            )}
            {!needsKey && (
              <div className="prov-local-note">
                <Server size={14} /> Ключ не нужен — AXIOM подключится к серверу на этом компьютере.
              </div>
            )}

            <button type="button" className={"prov-adv-toggle" + (advanced ? " open" : "")} onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>
              <ChevronDown size={13} /> Адрес сервера
              {!advanced && <code>{row.base_url || "не задан"}</code>}
            </button>
            {advanced && (
              <label className="prov-field">
                <span>Base URL{needsUrl ? " — обязательно" : ""}</span>
                <span className="prov-input">
                  <Server size={14} />
                  <input value={baseUrl} spellCheck={false} placeholder="https://api.example.com/v1" onChange={(e) => setBaseUrl(e.target.value)} />
                </span>
              </label>
            )}

            <div className="prov-actions">
              <span className="prov-actions-hint">{row.configured ? "Ключ хранится локально. Проверка обновит список моделей." : "После проверки появится список моделей."}</span>
              <button className="btn primary prov-connect" disabled={!canConnect} onClick={() => void onSave(row.id, key, baseUrl.trim())}>
                {loading ? <><Loader2 size={14} className="spin" /> Проверяем…</> : <><Zap size={14} /> {row.configured ? "Проверить снова" : "Подключить"}</>}
              </button>
            </div>
          </div>

          {/* step 2 — models */}
          <div className="prov-step">
            <div className="prov-step-head">
              <span className={"prov-step-num" + (providerModels.some((m) => m.model === activeModel) ? " done" : "")}>2</span>
              <strong>Выберите модель</strong>
              <span className="prov-step-count">{models.filter((m) => m.provider_id === row.id).length}</span>
            </div>
            {models.some((m) => m.provider_id === row.id) && (
              <label className="prov-search prov-search--models">
                <Search size={13} />
                <input value={modelFilter} onChange={(e) => setModelFilter(e.target.value)} placeholder="Фильтр моделей" spellCheck={false} />
              </label>
            )}
            <div className="prov-models">
              {providerModels.map((m) => {
                const active = m.model === activeModel;
                const ctx = fmtContext(m.context_length);
                return (
                  <button key={m.id} className={"prov-model" + (active ? " active" : "")} disabled={!!picking} onClick={() => void pick(m.model)}>
                    <span className="prov-model-radio">{active && <Check size={11} strokeWidth={3} />}</span>
                    <span className="prov-model-text">
                      <strong>{m.label}</strong>
                      <code>{m.model}</code>
                    </span>
                    <span className="prov-model-caps">
                      {m.capabilities.slice(0, 3).map((c) => <span key={c} className="prov-chip">{CAP_LABEL[c] ?? c}</span>)}
                    </span>
                    {ctx && <span className="prov-ctx" title="Контекстное окно">{ctx}</span>}
                    {picking === m.model && <Loader2 size={13} className="spin" />}
                  </button>
                );
              })}
              {!providerModels.length && (
                <div className="prov-models-empty">
                  {models.some((m) => m.provider_id === row.id) ? "Нет моделей по фильтру." : row.configured ? "Нажмите «Проверить снова», чтобы загрузить модели." : "Подключите провайдера — модели появятся здесь."}
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
