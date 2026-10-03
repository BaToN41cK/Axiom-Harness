import { useState } from "react";
import { Plus, RefreshCw, Server, Trash2, RotateCw, PlayCircle, Terminal } from "lucide-react";
import type { McpServerRow } from "../../types";
import { useLocale } from "../../lib/locale";

/** Split a shell-style command line into argv (honours double/single quotes). */
export function parseCommand(input: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(input)) !== null) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

type TestResult = { ok: boolean; content: string; error: string | null } | null;

function ServerCard({
  row,
  onRemove,
  onRestart,
  onTest,
}: {
  row: McpServerRow;
  onRemove: (name: string) => Promise<boolean>;
  onRestart: (name: string) => Promise<McpServerRow | null>;
  onTest: (name: string, tool?: string, argsJson?: string) => Promise<{ ok: boolean; content: string; error: string | null }>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<TestResult>(null);
  const { t } = useLocale();

  const runTest = async (tool?: string) => {
    setBusy(tool ? `test:${tool}` : "probe");
    setResult(null);
    setResult(await onTest(row.name, tool));
    setBusy(null);
  };

  return (
    <div className="mcp-card">
      <div className="mcp-card-head">
        <span className="mcp-card-title"><Server size={14} strokeWidth={1.8} />{row.name}</span>
        <span className={"mcp-status" + (row.ok ? " ok" : " err")}>
          {row.ok ? t("ui.mcp.connected") : t("ui.mcp.error")}
        </span>
      </div>
      <code className="mcp-command">{row.command.join(" ")}</code>
      {row.tools.length > 0 && (
        <div className="mcp-tools">
          {row.tools.map((tool) => (
            <button
              key={tool}
              className="mcp-tool"
              title={t("ui.mcp.test_tool", { tool })}
              disabled={busy !== null}
              onClick={() => void runTest(tool)}
            >
              <PlayCircle size={12} />{tool}
            </button>
          ))}
        </div>
      )}
      {row.error && <div className="mcp-log err">{row.error}</div>}
      {result && (
        <div className={"harness-result" + (result.ok ? " ok" : " err")}>
          <div className="harness-result-head">
            <Terminal size={13} /> {result.ok ? t("ui.mcp.test_result") : t("ui.mcp.test_error")}
          </div>
          <pre className="harness-result-body">{result.ok ? result.content || t("ui.mcp.empty_result") : result.error}</pre>
        </div>
      )}
      <div className="mcp-actions">
        <button className="btn ghost small" disabled={busy !== null} onClick={() => void runTest()}>
          {busy === "probe" ? t("ui.mcp.checking") : t("ui.mcp.test")}
        </button>
        <button className="btn ghost small" disabled={busy !== null} onClick={() => void onRestart(row.name)}>
          <RotateCw size={13} /> {t("ui.mcp.restart")}
        </button>
        <button className="btn danger small" onClick={() => void onRemove(row.name)}>
          <Trash2 size={13} /> {t("ui.common.delete")}
        </button>
      </div>
    </div>
  );
}

export default function McpPanel({
  rows,
  loading,
  onLoad,
  onAdd,
  onRemove,
  onRestart,
  onTest,
}: {
  rows: McpServerRow[];
  loading: boolean;
  onLoad: () => Promise<void>;
  onAdd: (name: string, command: string[]) => Promise<McpServerRow | null>;
  onRemove: (name: string) => Promise<boolean>;
  onRestart: (name: string) => Promise<McpServerRow | null>;
  onTest: (name: string, tool?: string, argsJson?: string) => Promise<{ ok: boolean; content: string; error: string | null }>;
}) {
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [adding, setAdding] = useState(false);
  const { t } = useLocale();

  const submit = async () => {
    const argv = parseCommand(command);
    if (!name.trim() || argv.length === 0) return;
    setAdding(true);
    await onAdd(name.trim(), argv);
    setAdding(false);
    setName("");
    setCommand("");
  };

  return (
    <div className="harness-panel">
      <div className="harness-toolbar">
        <p className="settings-row-hint">
          {t("ui.mcp.hint")}
        </p>
        <button className="btn ghost" disabled={loading} onClick={() => void onLoad()}>
          <RefreshCw size={13} strokeWidth={1.8} />
          {loading ? t("ui.common.refreshing") : t("ui.common.refresh")}
        </button>
      </div>

      <div className="mcp-form">
        <input className="mcp-input" placeholder={t("ui.mcp.name_placeholder")} value={name} onChange={(e) => setName(e.target.value)} />
        <input className="mcp-input grow" placeholder={t("ui.mcp.command_placeholder")} value={command} onChange={(e) => setCommand(e.target.value)} />
        <button className="btn primary" disabled={adding || !name.trim() || !command.trim()} onClick={() => void submit()}>
          <Plus size={13} /> {t("ui.mcp.add")}
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="settings-empty">
          {t("ui.mcp.empty")}
        </div>
      ) : (
        <div className="mcp-list">
          {rows.map((row) => (
            <ServerCard key={row.name} row={row} onRemove={onRemove} onRestart={onRestart} onTest={onTest} />
          ))}
        </div>
      )}
    </div>
  );
}
