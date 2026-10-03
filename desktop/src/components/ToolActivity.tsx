import { memo, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Ban, Check, ChevronRight, ClipboardCheck, FileCode2, FilePen, FilePlus2, FileSearch, FileText, FolderTree, GitBranch,
  Globe, Loader2, Search, SquareTerminal, Trash2, Wrench, X,
} from "lucide-react";
import type { ToolActivity } from "../types";
import { toolLabel } from "../hooks/useAxiom";
import { useLocale } from "../lib/locale";
import { plural as pluralCount, tVar } from "../lib/i18n";
import "../styles/tool-activity.css";

/* ================================================================ helpers */

type Kind = "read" | "edit" | "write" | "patch" | "search" | "files" | "list" | "run" | "checks" | "web" | "fetch" | "git" | "delete" | "other";

/** Verification tools (§34) — their own card kind, not plain commands. */
const CHECK_TOOLS = new Set(["run_tests", "run_linter", "build_project", "verify_changes"]);

function kindOf(name: string): Kind {
  if (CHECK_TOOLS.has(name)) return "checks";
  switch (name) {
    case "read_file": return "read";
    case "edit_file": return "edit";
    case "write_file": return "write";
    case "apply_patch": return "patch";
    case "search_text": return "search";
    case "search_files": return "files";
    case "list_files": case "inspect_project": return "list";
    case "run_command": case "terminal_run": return "run";
    case "web_search": return "web";
    case "fetch_url": return "fetch";
    case "delete_file": return "delete";
    default: return name.startsWith("git_") ? "git" : "other";
  }
}

const ICONS: Record<Kind, ReactNode> = {
  read: <FileText size={14} />, edit: <FilePen size={14} />, write: <FilePlus2 size={14} />, patch: <FileCode2 size={14} />,
  search: <Search size={14} />, files: <FileSearch size={14} />, list: <FolderTree size={14} />, run: <SquareTerminal size={14} />,
  checks: <ClipboardCheck size={14} />, web: <Globe size={14} />, fetch: <Globe size={14} />, git: <GitBranch size={14} />, delete: <Trash2 size={14} />, other: <Wrench size={14} />,
};

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const lines = (s: string): string[] => (s === "" ? [] : s.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n"));

/** Duration chip; units follow the core RU/EN catalog. */
function fmtMs(ms: number, locale: unknown, strings?: Record<string, string> | null): string {
  if (ms < 1000) return tVar("ui.summary.ms", locale, strings, { n: String(Math.round(ms)) });
  if (ms < 60_000) return tVar("ui.summary.sec", locale, strings, { n: (ms / 1000).toFixed(1) });
  return tVar("ui.summary.min", locale, strings, {
    n: String(Math.floor(ms / 60_000)),
    s: String(Math.round((ms % 60_000) / 1000)),
  });
}

/** Line diff (LCS) — exact for typical edit_file snippets, capped for huge inputs. */
type DiffLine = { t: " " | "+" | "-"; s: string };
function diffLines(a: string[], b: string[]): DiffLine[] {
  if (a.length * b.length > 250_000) return [...a.map((s) => ({ t: "-" as const, s })), ...b.map((s) => ({ t: "+" as const, s }))];
  const n = a.length, m = b.length;
  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ t: " ", s: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: "-", s: a[i++] });
    else out.push({ t: "+", s: b[j++] });
  }
  while (i < n) out.push({ t: "-", s: a[i++] });
  while (j < m) out.push({ t: "+", s: b[j++] });
  return out;
}

function splitPath(path: string): { dir: string; base: string } {
  const clean = path.replace(/\\/g, "/");
  const idx = clean.lastIndexOf("/");
  return idx < 0 ? { dir: "", base: clean } : { dir: clean.slice(0, idx + 1), base: clean.slice(idx + 1) };
}

function PathChip({ path }: { path: string }) {
  const { dir, base } = splitPath(path);
  return <span className="ta-path" title={path}>{dir && <span className="ta-path-dir">{dir}</span>}<b>{base}</b></span>;
}

function highlight(text: string, query: string): ReactNode {
  if (!query) return text;
  const lower = text.toLowerCase(), q = query.toLowerCase();
  const parts: ReactNode[] = [];
  let from = 0, k = 0;
  for (let at = lower.indexOf(q); at >= 0 && k < 20; at = lower.indexOf(q, at + q.length), k++) {
    parts.push(text.slice(from, at), <mark key={k}>{text.slice(at, at + q.length)}</mark>);
    from = at + q.length;
  }
  parts.push(text.slice(from));
  return parts;
}

/* ================================================================ bodies */

function CodeLines({ rows, start = 1, max = 40, kind }: { rows: DiffLine[] | string[]; start?: number; max?: number; kind?: "diff" | "plain" }) {
  const { t, locale, strings } = useLocale();
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, max);
  let lnA = start, lnB = start;
  return (
    <div className="ta-code">
      <table>
        <tbody>
          {shown.map((row, index) => {
            if (typeof row === "string") {
              return <tr key={index}><td className="ta-ln">{start + index}</td><td className="ta-src">{row || " "}</td></tr>;
            }
            const a = row.t === "+" ? "" : lnA++;
            const b = row.t === "-" ? "" : lnB++;
            return (
              <tr key={index} className={row.t === "+" ? "add" : row.t === "-" ? "del" : ""}>
                {kind === "diff" && <td className="ta-ln">{a}</td>}
                <td className="ta-ln">{b}</td>
                <td className="ta-sign">{row.t === " " ? "" : row.t}</td>
                <td className="ta-src">{row.s || " "}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length > max && (
        <button className="ta-more" onClick={() => setAll(!all)}>
          {all ? t("ui.summary.collapse") : pluralCount("ui.summary.more", rows.length - max, locale, strings)}
        </button>
      )}
    </div>
  );
}

function SearchBody({ output, query }: { output: string; query: string }) {
  const { locale, strings, t } = useLocale();
  const groups = useMemo(() => {
    const map = new Map<string, { line: string; text: string }[]>();
    for (const raw of lines(output).slice(0, 400)) {
      const m = /^(.+?):(\d+):\s?(.*)$/.exec(raw);
      if (!m) continue;
      const list = map.get(m[1]) ?? [];
      list.push({ line: m[2], text: m[3] });
      map.set(m[1], list);
    }
    return [...map.entries()];
  }, [output]);
  if (!groups.length) return <pre className="ta-pre">{output.slice(0, 4000) || t("ui.summary.no_matches")}</pre>;
  return (
    <div className="ta-search">
      {groups.slice(0, 12).map(([file, hits]) => (
        <div key={file} className="ta-search-file">
          <div className="ta-search-head"><FileText size={12} /><PathChip path={file} /><span className="ta-count">{hits.length}</span></div>
          {hits.slice(0, 6).map((h, i) => (
            <div key={i} className="ta-search-hit"><span className="ta-ln">{h.line}</span><code>{highlight(h.text.trim(), query)}</code></div>
          ))}
          {hits.length > 6 && <div className="ta-search-rest">{tVar("ui.summary.more_hits", locale, strings, { k: String(hits.length - 6) })}</div>}
        </div>
      ))}
      {groups.length > 12 && <div className="ta-search-rest">{pluralCount("ui.summary.more_files", groups.length - 12, locale, strings)}</div>}
    </div>
  );
}

function FileListBody({ output }: { output: string }) {
  const items = lines(output).map((l) => l.trim()).filter(Boolean).slice(0, 60);
  if (!items.length) return null;
  return (
    <div className="ta-files">
      {items.map((item, i) => {
        const isDir = item.endsWith("/");
        return <span key={i} className={"ta-file" + (isDir ? " dir" : "")}>{isDir ? <FolderTree size={11} /> : <FileText size={11} />}{item}</span>;
      })}
    </div>
  );
}

function TerminalBody({ command, output, failed }: { command: string; output: string; failed: boolean }) {
  const { t, locale, strings } = useLocale();
  const out = lines(output);
  const tail = out.slice(-60);
  return (
    <div className={"ta-term" + (failed ? " failed" : "")}>
      <div className="ta-term-bar"><span /><span /><span /><em>{t("ui.summary.terminal")}</em></div>
      <pre><span className="ta-prompt">$</span> {command}{"\n"}{out.length > 60 ? `${pluralCount("ui.summary.hidden", out.length - 60, locale, strings)}\n` : ""}{tail.join("\n")}</pre>
    </div>
  );
}

/* ================================================================ card */

interface Summary { stat?: ReactNode; body?: ReactNode; target?: ReactNode; openByDefault?: boolean }

function summarize(call: ToolActivity, locale: unknown, strings?: Record<string, string> | null): Summary {
  const k = kindOf(call.name);
  const a = call.args ?? {};
  const out = call.output ?? "";
  const path = str(a.path) || str(a.source);
  switch (k) {
    case "edit": {
      const d = diffLines(lines(str(a.old_text)), lines(str(a.new_text)));
      const add = d.filter((x) => x.t === "+").length, del = d.filter((x) => x.t === "-").length;
      return {
        target: path ? <PathChip path={path} /> : call.detail,
        stat: d.length ? <span className="ta-delta"><b className="add">+{add}</b><b className="del">−{del}</b></span> : null,
        body: d.length ? <CodeLines rows={d} kind="diff" max={30} /> : null,
        openByDefault: d.length > 0 && d.length <= 30,
      };
    }
    case "write": {
      const body = lines(str(a.content));
      return {
        target: path ? <PathChip path={path} /> : call.detail,
        stat: body.length ? <span className="ta-delta"><b className="add">+{body.length}</b></span> : null,
        body: body.length ? <CodeLines rows={body.map((s) => ({ t: "+" as const, s }))} max={18} /> : null,
        openByDefault: body.length > 0 && body.length <= 18,
      };
    }
    case "patch": {
      const rows = lines(str(a.patch)).map((s) => ({ t: (s.startsWith("+") && !s.startsWith("+++") ? "+" : s.startsWith("-") && !s.startsWith("---") ? "-" : " ") as DiffLine["t"], s: /^[+\- ]/.test(s) ? s.slice(1) : s }));
      const add = rows.filter((x) => x.t === "+").length, del = rows.filter((x) => x.t === "-").length;
      return { target: path ? <PathChip path={path} /> : call.detail, stat: <span className="ta-delta"><b className="add">+{add}</b><b className="del">−{del}</b></span>, body: rows.length ? <CodeLines rows={rows} kind="diff" max={30} /> : null };
    }
    case "read": {
      const s = Number(a.start_line) || 0, e = Number(a.end_line) || 0;
      const range = s
        ? e
          ? tVar("ui.summary.lines", locale, strings, { s: String(s), e: String(e) })
          : tVar("ui.summary.lines_from", locale, strings, { s: String(s) })
        : null;
      const textLines = lines(out).slice(0, 400).map((l) => l.replace(/^\s*\d+[:|\t]\s?/, ""));
      return {
        target: path ? <PathChip path={path} /> : call.detail,
        stat: range ? <span className="ta-meta">{range}</span> : out ? <span className="ta-meta">{pluralCount("ui.summary.line", lines(out).length, locale, strings)}</span> : null,
        body: textLines.length ? <CodeLines rows={textLines} start={s || 1} max={14} /> : null,
      };
    }
    case "search": {
      const q = str(a.query);
      const hits = lines(out).filter((l) => /^.+?:\d+:/.test(l)).length;
      return {
        target: <span className="ta-query">«{q}»{str(a.glob) && <em> {tVar("ui.summary.in_glob", locale, strings, { glob: str(a.glob) })}</em>}</span>,
        stat: call.state === "ok" ? <span className="ta-meta">{pluralCount("ui.summary.match", hits, locale, strings)}</span> : null,
        body: out ? <SearchBody output={out} query={q} /> : null,
        openByDefault: hits > 0 && hits <= 12,
      };
    }
    case "files":
    case "list": {
      const n = lines(out).filter((l) => l.trim()).length;
      return {
        target: k === "files" ? <span className="ta-query">{str(a.pattern) || call.detail}</span> : path ? <PathChip path={path || "."} /> : call.detail,
        stat: out ? <span className="ta-meta">{pluralCount("ui.summary.item", n, locale, strings)}</span> : null,
        body: out ? <FileListBody output={out} /> : null,
      };
    }
    case "run": {
      const cmd = str(a.command) || call.detail;
      return { target: <code className="ta-cmd">{cmd}</code>, body: <TerminalBody command={cmd} output={out} failed={call.state === "failed"} />, openByDefault: call.state === "running" || call.state === "failed" };
    }
    case "checks": {
      // Verification tools (§34): the concise verdict shows immediately;
      // the full step output (BUILD/TEST/LINT) is expandable.
      const failed = call.state === "failed";
      const verdict = failed
        ? tVar("ui.toolgroup.check_failed", locale, strings, {})
        : call.state === "ok"
          ? tVar("ui.toolgroup.check_passed", locale, strings, {})
          : null;
      return {
        target: <span className="ta-query">{toolLabel(call.name, locale, strings)}</span>,
        stat: verdict ? <span className={"ta-meta" + (failed ? " failed" : "")}>{verdict}</span> : null,
        body: out ? <TerminalBody command={call.name} output={out} failed={failed} /> : null,
        openByDefault: failed,
      };
    }
    case "delete":
      return { target: path ? <PathChip path={path} /> : call.detail };
    default:
      return { target: call.detail || null, body: out ? <pre className="ta-pre">{out.slice(0, 3000)}</pre> : null };
  }
}

const ToolCard = memo(function ToolCard({ call, last }: { call: ToolActivity; last: boolean }) {
  const { locale, strings, t } = useLocale();
  const k = kindOf(call.name);
  const info = summarize(call, locale, strings);
  const [open, setOpen] = useState<boolean | null>(null);
  const [showArgs, setShowArgs] = useState(false);
  const isOpen = open ?? (!!info.openByDefault || call.state === "failed");
  const argKeys = call.args ? Object.keys(call.args) : [];
  // Result preview renders first; the raw arguments sit behind their own toggle
  // so the collapsed card stays concise (agent-action cards, §5).
  const hasBody = !!info.body || (call.state === "failed" && !!call.error) || argKeys.length > 0;
  return (
    <li className={`ta-item ta-k-${k} ${call.state}` + (last ? " last" : "")}>
      <span className="ta-node">{call.state === "running" ? <Loader2 size={13} className="spin" /> : ICONS[k]}</span>
      <div className="ta-card">
        <button className="ta-head" onClick={() => hasBody && setOpen(!isOpen)} aria-expanded={hasBody ? isOpen : undefined} disabled={!hasBody}>
          <span className="ta-label">{toolLabel(call.name, locale, strings)}</span>
          <span className="ta-target">{info.target}</span>
          {info.stat}
          <span className="ta-state">
            {call.state === "ok" && <Check size={12} strokeWidth={2.6} />}
            {call.state === "failed" && <X size={12} strokeWidth={2.6} />}
            {call.state === "cancelled" && <Ban size={12} />}
            {call.durationMs != null && call.state !== "running" && <span>{fmtMs(call.durationMs, locale, strings)}</span>}
          </span>
          {hasBody && <ChevronRight size={13} className={"ta-chev" + (isOpen ? " open" : "")} />}
        </button>
        {isOpen && hasBody && (
          <div className="ta-body">
            {call.state === "failed" && call.error && <div className="ta-error">{call.error}</div>}
            {info.body}
            {argKeys.length > 0 && (
              <div className="ta-args">
                <button className="ta-more" onClick={() => setShowArgs(!showArgs)}>
                  {showArgs ? t("ui.summary.collapse") : t("ui.toolcall.args")}
                </button>
                {showArgs && <pre className="ta-pre">{JSON.stringify(call.args, null, 2)}</pre>}
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
});

/** Summary chips: what the agent did this turn. */
function Overview({ calls }: { calls: ToolActivity[] }) {
  const { t, locale, strings } = useLocale();
  const count = (pred: (k: Kind) => boolean) => calls.filter((c) => pred(kindOf(c.name))).length;
  const items: [number, string, ReactNode][] = [
    [count((k) => k === "read"), t("ui.toolgroup.read"), <FileText size={12} key="r" />],
    [count((k) => k === "edit" || k === "write" || k === "patch"), t("ui.toolgroup.edit"), <FilePen size={12} key="e" />],
    [count((k) => k === "search" || k === "files" || k === "list"), t("ui.toolgroup.search"), <Search size={12} key="s" />],
    [count((k) => k === "run"), t("ui.toolgroup.run"), <SquareTerminal size={12} key="c" />],
    [count((k) => k === "checks"), t("ui.toolgroup.checks"), <ClipboardCheck size={12} key="v" />],
    [count((k) => k === "web" || k === "fetch"), t("ui.toolgroup.web"), <Globe size={12} key="w" />],
  ];
  const running = calls.some((c) => c.state === "running");
  const failed = calls.filter((c) => c.state === "failed").length;
  return (
    <div className="ta-overview">
      <span className={"ta-overview-dot" + (running ? " live" : "")} />
      <strong>{running ? t("ui.overview.working") : t("ui.overview.actions")}</strong>
      {items.filter(([n]) => n > 0).map(([n, label, icon]) => (
        <span key={label} className="ta-chip">{icon}{label}<b>{n}</b></span>
      ))}
      {failed > 0 && <span className="ta-chip bad"><X size={12} />{pluralCount("ui.overview.error", failed, locale, strings)}</span>}
    </div>
  );
}

/** Rich, timeline-style tool activity for an assistant message. */
export function ToolActivityTimeline({ calls }: { calls: ToolActivity[] }) {
  if (!calls.length) return null;
  return (
    <div className="ta">
      {calls.length >= 2 && <Overview calls={calls} />}
      <ol className="ta-list">
        {calls.map((call, index) => <ToolCard key={`${call.name}-${index}`} call={call} last={index === calls.length - 1} />)}
      </ol>
    </div>
  );
}
