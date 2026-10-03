import { Check, ChevronDown, Globe, Loader2, TriangleAlert, X, Ban, FileText, ExternalLink } from "lucide-react";
import { useState } from "react";
import type { SourceItem, ToolActivity } from "../types";
import { toolLabel } from "../hooks/useAxiom";
import { useLocale } from "../lib/locale";

/** Host of a URL for display ("" when the URL is unparsable). */
export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

/** Path+query of a URL without the host — the second half of a pretty link. */
export function pathOf(url: string): string {
  try {
    const parsed = new URL(url);
    return (parsed.pathname === "/" ? "" : parsed.pathname) + parsed.search;
  } catch {
    return "";
  }
}

/** Site favicon with a letter-tile fallback (offline or icon blocked). */
export function Favicon({ url, size = 14 }: { url: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const host = hostOf(url);
  const letter = (host.replace(/^www\./, "")[0] ?? "?").toUpperCase();
  if (!host || failed) {
    return (
      <span
        className="favicon-fallback"
        style={{ width: size, height: size, fontSize: Math.round(size * 0.55) }}
        aria-hidden="true"
      >
        {letter}
      </span>
    );
  }
  return (
    <img
      className="favicon"
      style={{ width: size, height: size }}
      src={`https://icons.duckduckgo.com/ip3/${host}.ico`}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

interface ToolProps {
  calls: ToolActivity[];
}

function ToolGlyph({ name }: { name: string }) {
  if (name === "web_search") return <Globe size={13} strokeWidth={1.8} />;
  if (name === "fetch_url") return <FileText size={13} strokeWidth={1.8} />;
  return <Globe size={13} strokeWidth={1.8} />;
}

/** Tool activity with real running / success / failed / cancelled states. */
export function ToolActivityList({ calls }: ToolProps) {
  const { t, locale, strings } = useLocale();
  if (calls.length === 0) return null;
  return (
    <div className="tool-list">
      {calls.map((call, index) => (
        <details key={`${call.name}-${index}`} className={"tool-card " + call.state} open={call.state === "running" || call.state === "failed"}>
          <summary className="tool-card-head">
            <span className="tool-icon">
              <ToolGlyph name={call.name} />
            </span>
            <span className="tool-name">{toolLabel(call.name, locale, strings)}</span>
            <span className="tool-state">
              {call.state === "running" && (
                <>
                  <Loader2 size={12} className="spin" /> {t("ui.toolbits.running")}
                </>
              )}
              {call.state === "ok" && (
                <>
                  <Check size={12} strokeWidth={2.3} /> {t("ui.toolbits.done")}
                </>
              )}
              {call.state === "failed" && (
                <>
                  <X size={12} strokeWidth={2.3} /> {t("ui.toolbits.error")}
                </>
              )}
              {call.state === "cancelled" && (
                <>
                  <Ban size={12} strokeWidth={2.1} /> {t("ui.toolbits.cancelled")}
                </>
              )}
              {call.durationMs != null && call.state !== "running" && (
                <span className="tool-duration">{call.durationMs} ms</span>
              )}
            </span>
          </summary>
          {call.detail && <div className="tool-target">{call.detail}</div>}
          {call.state === "failed" && call.error && <div className="tool-error">{call.error}</div>}
        </details>
      ))}
    </div>
  );
}

interface SourcesProps {
  sources: SourceItem[];
  onOpen: (url: string) => void;
}

/** Real search results — rendered as preview cards: index, favicon, title, url, snippet. */
export function SourcesList({ sources, onOpen }: SourcesProps) {
  const [open, setOpen] = useState(true);
  const { t } = useLocale();
  if (sources.length === 0) return null;
  return (
    <div className="sources">
      <button className="sources-toggle" onClick={() => setOpen((v) => !v)}>
        <Globe size={13} strokeWidth={1.8} />
        <span>
          {t("ui.toolbits.sources", { n: String(sources.length) })}
        </span>
        <ChevronDown size={13} strokeWidth={1.8} className={"chevron" + (open ? " open" : "")} />
      </button>
      {open && (
        <ol className="sources-list">
          {sources.map((source) => {
            const host = hostOf(source.url);
            const path = pathOf(source.url);
            return (
              <li key={`${source.index}-${source.url}`}>
                <button
                  className="source-card"
                  onClick={() => onOpen(source.url)}
                  title={source.url}
                >
                  <span className="source-card-head">
                    <span className="source-index">{source.index}</span>
                    <Favicon url={source.url} />
                    <span className="source-title">{source.title || source.url}</span>
                    <ExternalLink size={12} strokeWidth={1.8} className="source-open" />
                  </span>
                  <span className="source-url">
                    <b>{host}</b>
                    {path}
                  </span>
                  {source.snippet && (
                    <>
                      <span className="source-divider" />
                      <span className="source-snippet">{source.snippet}</span>
                    </>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

export function MessageError({ message, hint }: { message: string; hint: string | null }) {
  return (
    <div className="msg-error">
      <TriangleAlert size={15} strokeWidth={1.9} />
      <div>
        <div className="msg-error-title">{message}</div>
        {hint && <div className="msg-error-hint">{hint}</div>}
      </div>
    </div>
  );
}