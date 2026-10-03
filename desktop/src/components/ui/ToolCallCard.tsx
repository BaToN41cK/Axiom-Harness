import { useState } from "react";
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { StatusPill } from "./Status";
import type { PillState } from "./Status";
import { useLocale } from "../../lib/locale";

export type ToolCardState = PillState;

const STATE_LABEL: Record<ToolCardState, string> = {
  idle: "ui.toolcall.idle",
  queued: "ui.toolcall.queued",
  running: "ui.toolcall.running",
  completed: "ui.toolcall.completed",
  failed: "ui.toolcall.failed",
  denied: "ui.toolcall.denied",
  cancelled: "ui.toolcall.cancelled",
};

interface ToolCallCardProps {
  icon?: ReactNode;
  /** What the agent did: "Read 12 files", "npm test". */
  title: ReactNode;
  /** The concrete target: path, command, query. Monospace. */
  subtitle?: ReactNode;
  state: ToolCardState;
  /** Real measured duration in ms. Omitted while running or unknown. */
  durationMs?: number | null;
  /** Arguments of the call, rendered on expand. */
  args?: Record<string, unknown> | null;
  stdout?: string | null;
  stderr?: string | null;
  error?: string | null;
  /** Extra rows rendered inside the expanded body (diff links, counts). */
  children?: ReactNode;
  /** Group size when consecutive identical calls are folded together. */
  groupCount?: number;
  defaultOpen?: boolean;
  className?: string;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

/**
 * One tool invocation as the user sees it: what ran, how it ended, how long it
 * took, and — on demand — the exact arguments and output.
 *
 * Nothing here is inferred: a missing duration renders as nothing rather than
 * an estimate, and stdout/stderr sections appear only when the core sent them.
 */
export function ToolCallCard({
  icon,
  title,
  subtitle,
  state,
  durationMs,
  args,
  stdout,
  stderr,
  error,
  children,
  groupCount,
  defaultOpen = false,
  className = "",
}: ToolCallCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const { t } = useLocale();
  const hasDetails =
    !!children ||
    !!error ||
    (!!args && Object.keys(args).length > 0) ||
    !!(stdout && stdout.trim()) ||
    !!(stderr && stderr.trim());

  return (
    <div
      className={["ax-tool", `ax-tool-${state}`, open ? "is-open" : "", className]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="ax-tool-head">
        {hasDetails ? (
          <button
            type="button"
            className="ax-tool-toggle"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            <ChevronRight size={13} strokeWidth={2} aria-hidden />
            <span className="ax-sr-only">
              {open ? t("ui.toolcall.hide_details") : t("ui.toolcall.show_details")}
            </span>
          </button>
        ) : (
          <span className="ax-tool-toggle is-static" aria-hidden />
        )}
        {icon && <span className="ax-tool-icon">{icon}</span>}
        <div className="ax-tool-title">
          <span className="ax-tool-name">
            {title}
            {groupCount != null && groupCount > 1 && (
              <span className="ax-tool-group">×{groupCount}</span>
            )}
          </span>
          {subtitle && <span className="ax-tool-target">{subtitle}</span>}
        </div>
        <StatusPill state={state} label={t(STATE_LABEL[state])} className="ax-tool-state" />
        {durationMs != null && state !== "running" && (
          <span className="ax-tool-duration" title={t("ui.toolcall.duration")}>
            {formatDuration(durationMs)}
          </span>
        )}
      </div>

      {open && hasDetails && (
        <div className="ax-tool-body">
          {error && (
            <section className="ax-tool-section is-error">
              <h4>{t("ui.toolcall.error")}</h4>
              <pre>{error}</pre>
            </section>
          )}
          {args && Object.keys(args).length > 0 && (
            <section className="ax-tool-section">
              <h4>{t("ui.toolcall.args")}</h4>
              <pre>{JSON.stringify(args, null, 2)}</pre>
            </section>
          )}
          {stdout && stdout.trim() && (
            <section className="ax-tool-section">
              <h4>stdout</h4>
              <pre>{stdout}</pre>
            </section>
          )}
          {stderr && stderr.trim() && (
            <section className="ax-tool-section is-error">
              <h4>stderr</h4>
              <pre>{stderr}</pre>
            </section>
          )}
          {children}
        </div>
      )}
    </div>
  );
}
