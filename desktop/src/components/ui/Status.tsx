import type { ReactNode } from "react";
import { AlertTriangle, Check, CircleSlash, Info, Loader2, XCircle } from "lucide-react";

export type StatusTone = "neutral" | "accent" | "success" | "warning" | "info" | "error";

interface BadgeProps {
  children: ReactNode;
  tone?: StatusTone;
  /** Renders a counter-style badge (sessions per day group, tab counts). */
  count?: boolean;
  className?: string;
  title?: string;
}

/** Small neutral label. Counts and group sizes use `count`. */
export function Badge({ children, tone = "neutral", count = false, className = "", title }: BadgeProps) {
  return (
    <span
      className={["ax-badge", `ax-tone-${tone}`, count ? "ax-badge-count" : "", className]
        .filter(Boolean)
        .join(" ")}
      title={title}
    >
      {children}
    </span>
  );
}

export type PillState =
  | "idle"
  | "running"
  | "queued"
  | "completed"
  | "failed"
  | "denied"
  | "cancelled";

const PILL_TONE: Record<PillState, StatusTone> = {
  idle: "neutral",
  running: "info",
  queued: "neutral",
  completed: "success",
  failed: "error",
  denied: "warning",
  cancelled: "neutral",
};

function StateIcon({ state, size = 12 }: { state: PillState; size?: number }) {
  const common = { size, strokeWidth: 2, "aria-hidden": true } as const;
  switch (state) {
    case "running":
      return <Loader2 className="ax-spin" {...common} />;
    case "completed":
      return <Check {...common} />;
    case "failed":
      return <XCircle {...common} />;
    case "denied":
      return <CircleSlash {...common} />;
    case "cancelled":
      return <CircleSlash {...common} />;
    case "queued":
      return <Info {...common} />;
    default:
      return null;
  }
}

interface StatusPillProps {
  /** Always visible text: a status is never colour-only. */
  label: ReactNode;
  state?: PillState;
  tone?: StatusTone;
  /** Shows a leading dot instead of an icon (connection-style indicators). */
  dot?: boolean;
  icon?: ReactNode;
  title?: string;
  className?: string;
}

/**
 * Status indicator with an icon (or dot) plus text, so meaning never depends
 * on colour alone. `state` picks the tone; `tone` can override it.
 */
export function StatusPill({
  label,
  state = "idle",
  tone,
  dot = false,
  icon,
  title,
  className = "",
}: StatusPillProps) {
  const resolved = tone ?? PILL_TONE[state];
  return (
    <span
      className={["ax-pill", `ax-tone-${resolved}`, className].filter(Boolean).join(" ")}
      title={title}
    >
      {dot ? <span className="ax-pill-dot" aria-hidden /> : (icon ?? <StateIcon state={state} />)}
      <span className="ax-pill-label">{label}</span>
    </span>
  );
}

/**
 * Inline error banner. Errors always carry an icon and text, and use the error
 * hue rather than the accent.
 */
export function ErrorNote({
  message,
  hint,
  className = "",
}: {
  message: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={"ax-error-note" + (className ? ` ${className}` : "")} role="alert">
      <AlertTriangle size={14} strokeWidth={2} aria-hidden />
      <div className="ax-error-note-body">
        <strong>{message}</strong>
        {hint && <span>{hint}</span>}
      </div>
    </div>
  );
}
