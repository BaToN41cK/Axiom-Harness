import { Activity, AlertTriangle, Globe, Info, Loader2, RefreshCw, X, Wrench } from "lucide-react";
import type { AgentRow, ModelInfo, ProviderRow, StatusReport, ToolInfo, TrajectoryViewer } from "../types";
import { SHORTCUTS, COMMANDS, localizedDescription, localizedArgumentHint, localizedShortcutLabel } from "../lib/commands";
import { formatCount, formatDuration, formatBytes } from "../lib/format";
import { useLocale } from "../lib/locale";
import type { Overlay } from "../hooks/useAxiom";

interface ContextInfo {
  window: number | null;
  numCtx: number | null;
  used: number | null;
  ratio: number | null;
  turns: number;
  images: number;
  toolCalls: number;
  sources: number;
}

interface Props {
  overlay: Overlay;
  onClose: () => void;
  model: ModelInfo | null;
  context: ContextInfo;
  status: StatusReport | null;
  statusError: string | null;
  tools: ToolInfo[] | null;
  toolsError: string | null;
  onReload: () => void;
  agents: AgentRow[];
  providers: ProviderRow[];
  trajectory: TrajectoryViewer | null;
}

const STATE_LABELS: Record<string, string> = {
  idle: "ui.state.idle",
  connecting: "ui.live.connecting",
  thinking: "ui.live.thinking",
  tool_call: "ui.live.tool_call",
  searching: "ui.live.searching",
  receiving: "ui.live.receiving",
  completed: "ui.state.completed",
  cancelled: "ui.live.cancelled",
  error: "ui.live.error",
};

const TITLE_KEY: Record<string, string> = {
  help: "ui.overlay.title.help",
  status: "ui.overlay.title.status",
  tools: "ui.overlay.title.tools",
  harness: "ui.overlay.title.status",
  context: "ui.overlay.title.context",
};

export default function OverlayPanel(props: Props) {
  const { overlay, onClose, model, context, status, statusError, tools, toolsError, onReload, agents, providers, trajectory } = props;
  const { t } = useLocale();
  if (!overlay) return null;

  const title = overlay === "harness" ? "Harness" : t(TITLE_KEY[overlay] ?? "ui.overlay.title.status");

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={"modal panel-" + overlay} onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h2>{title}</h2>
          <div className="modal-head-actions">
            {(overlay === "status" || overlay === "tools" || overlay === "context") && (
              <button className="icon-btn" onClick={onReload} title={t("ui.overlay.refresh")}>
                <RefreshCw size={15} strokeWidth={1.8} />
              </button>
            )}
            <button className="icon-btn" onClick={onClose} title={t("ui.overlay.close")}>
              <X size={16} strokeWidth={1.8} />
            </button>
          </div>
        </div>
        <div className="modal-body">
          {overlay === "help" && <HelpBody />}
          {overlay === "status" && (
            <StatusBody status={status} error={statusError} model={model} />
          )}
          {overlay === "tools" && <ToolsBody tools={tools} error={toolsError} model={model} />}
          {overlay === "context" && <ContextBody context={context} model={model} />}
          {overlay === "harness" && <HarnessBody agents={agents} providers={providers} trajectory={trajectory} />}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  );
}

function HelpBody() {
  // W3.8: command/shortcut texts follow the core RU/EN catalog.
  const { t } = useLocale();
  const tt = (key: string) => t(key);
  return (
    <div className="help">
      <div className="help-section">
        <div className="help-title">
          <Info size={14} strokeWidth={1.8} /> {t("ui.help.commands")}
        </div>
        <div className="help-grid">
          {COMMANDS.map((command) => (
            <div key={command.name} className="help-row">
              <code>
                {command.name}
                {localizedArgumentHint(command, tt) ? ` ${localizedArgumentHint(command, tt)}` : ""}
              </code>
              <span>{localizedDescription(command, tt)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="help-section">
        <div className="help-title">
          <Activity size={14} strokeWidth={1.8} /> {t("ui.help.shortcuts")}
        </div>
        <div className="help-grid">
          {SHORTCUTS.map((shortcut) => (
            <div key={shortcut.keys} className="help-row">
              <kbd>{shortcut.keys}</kbd>
              <span>{localizedShortcutLabel(shortcut, tt)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="help-note">
        {t("ui.help.note")}
      </div>
    </div>
  );
}

function StatusBody({
  status,
  error,
  model,
}: {
  status: StatusReport | null;
  error: string | null;
  model: ModelInfo | null;
}) {
  const { t } = useLocale();
  if (error) {
    return (
      <div className="panel-error">
        <AlertTriangle size={15} strokeWidth={1.9} />
        <span>{error}</span>
      </div>
    );
  }
  if (!status) {
    return (
      <div className="panel-loading">
        <Loader2 size={15} className="spin" /> {t("ui.overlay.reading_status")}
      </div>
    );
  }
  const metrics = status.lastMetrics ?? {};
  return (
    <div className="info-list">
      <Row label="Ollama" value={status.ollamaUrl} />
      <Row label={t("ui.overlay.ollama_version")} value={status.version ?? t("ui.overlay.unavailable")} />
      <Row label={t("ui.overlay.state")} value={t(STATE_LABELS[status.state] ?? "") || status.state} />
      <Row label={t("ui.settings.about.active_model")} value={status.activeModel?.displayName ?? model?.displayName ?? "—"} />
      <Row label={t("ui.overlay.generation")} value={status.busy ? t("ui.overlay.running") : t("ui.overlay.not_running")} />
      <Row label={t("ui.overlay.history_count")} value={String(status.historyCount)} />
      <Row label={t("ui.overlay.config")} value={<code>{status.configPath}</code>} />
      {metrics.tokensOut != null && <Row label={t("ui.overlay.tokens_out")} value={String(metrics.tokensOut)} />}
      {metrics.tokensIn != null && <Row label={t("ui.overlay.tokens_in")} value={String(metrics.tokensIn)} />}
      {metrics.tokensPerSecond != null && (
        <Row label={t("ui.overlay.speed")} value={`${metrics.tokensPerSecond.toFixed(1)} tok/s`} />
      )}
      {metrics.durationMs != null && <Row label={t("ui.overlay.duration")} value={formatDuration(metrics.durationMs)} />}
    </div>
  );
}

function ToolsBody({
  tools,
  error,
  model,
}: {
  tools: ToolInfo[] | null;
  error: string | null;
  model: ModelInfo | null;
}) {
  const { t } = useLocale();
  const canUseTools = model ? model.capabilities.includes("tools") : null;
  return (
    <div className="info-list">
      {canUseTools === false && (
        <div className="panel-note">
          <AlertTriangle size={14} strokeWidth={1.9} />
          <span>
            {model?.displayName ?? t("ui.overlay.current_model")} {t("ui.overlay.no_tools")}
          </span>
        </div>
      )}
      {error && (
        <div className="panel-error">
          <AlertTriangle size={15} strokeWidth={1.9} />
          <span>{error}</span>
        </div>
      )}
      {!error && !tools && (
        <div className="panel-loading">
          <Loader2 size={15} className="spin" /> {t("ui.overlay.reading_tools")}
        </div>
      )}
      {tools?.map((tool) => (
        <div key={tool.name} className="tool-row">
          <div className="tool-row-head">
            <Wrench size={14} strokeWidth={1.8} />
            <code>{tool.name}</code>
            <span className="tool-perm">{tool.permission}</span>
          </div>
          <div className="tool-desc">{tool.description}</div>
        </div>
      ))}
      {tools && tools.length === 0 && <Row label={t("ui.overlay.title.tools")} value={t("ui.overlay.tools_none")} />}
    </div>
  );
}

function ContextBody({ context, model }: { context: ContextInfo; model: ModelInfo | null }) {
  const { t } = useLocale();
  const bar = context.ratio == null ? null : Math.round(context.ratio * 100);
  return (
    <div className="info-list">
      <Row label={t("ui.settings.about.active_model")} value={model?.displayName ?? "—"} />
      <Row
        label={t("ui.overlay.context_window")}
        value={context.window != null ? `${formatCount(context.window)} ${t("ui.overlay.tokens")}` : t("ui.overlay.model_no_report")}
      />
      {context.numCtx != null && <Row label="num_ctx" value={formatCount(context.numCtx)} />}
      <Row
        label={t("ui.overlay.used_prompt")}
        value={context.used != null ? `${formatCount(context.used)} ${t("ui.overlay.tokens")}` : "—"}
      />
      {bar != null && (
        <div className="ctx-bar-row">
          <div className="ctx-bar">
            <div className="ctx-bar-fill" style={{ width: `${bar}%` }} />
          </div>
          <span className="ctx-bar-label">{bar}%</span>
        </div>
      )}
      <Row label={t("ui.overlay.messages")} value={String(context.turns)} />
      <Row label={t("ui.overlay.files_images")} value={String(context.images)} />
      <Row label={t("ui.overlay.tool_calls")} value={String(context.toolCalls)} />
      <Row label={t("ui.overlay.sources")} value={String(context.sources)} />
      {context.used == null && (
        <div className="panel-note">
          <Globe size={14} strokeWidth={1.8} />
          <span>{t("ui.overlay.ctx_note")}</span>

        </div>
      )}
      <Row label={t("ui.overlay.model_size")} value={formatBytes(model?.sizeBytes ?? null) || "—"} />
      <Row label={t("ui.overlay.parameters")} value={model?.parameterSize || "—"} />
      <Row label={t("ui.overlay.quantization")} value={model?.quantization || "—"} />
    </div>
  );
}

function HarnessBody({ agents, providers, trajectory }: { agents: AgentRow[]; providers: ProviderRow[]; trajectory: TrajectoryViewer | null }) {
  return <div className="info-list">
    <div className="help-section"><div className="help-title">Permissions</div><div className="panel-note">ask · auto_approve_safe · auto_approve_all</div></div>
    <div className="help-section"><div className="help-title">Providers</div>{providers.map((p) => <div className="info-row" key={p.id}><span className="info-label">{p.label}</span><span className="info-value">{p.status}</span></div>)}</div>
    <div className="help-section"><div className="help-title">Agents</div>{agents.map((a) => <div className="info-row" key={a.id}><span className="info-label">{a.label}</span><span className="info-value">{a.provider_id}/{a.model || "auto"}</span></div>)}</div>
    <div className="help-section"><div className="help-title">Trajectory</div>{(trajectory?.lines ?? []).slice(-30).map((e) => <div className="info-row" key={e.seq}><span className="info-label">{e.time} · {e.kind}</span><span className="info-value">{e.summary}</span></div>)}</div>
  </div>;
}
