import type { ReactNode } from "react";
import { useLocale } from "../../lib/locale";

interface CardProps {
  children: ReactNode;
  /** `flat` sits on the panel, `elevated` lifts with a border + shadow. */
  variant?: "flat" | "elevated" | "inset";
  /** Accent border for the selected/active card. */
  selected?: boolean;
  className?: string;
  as?: "div" | "li" | "section" | "article";
}

/** Neutral container. Elevation is border + shadow, never a glow. */
export function Card({
  children,
  variant = "flat",
  selected = false,
  className = "",
  as: Tag = "div",
}: CardProps) {
  return (
    <Tag
      className={["ax-card", `ax-card-${variant}`, selected ? "is-selected" : "", className]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Tag>
  );
}

/** Card header with a title row and optional trailing actions. */
export function CardHeader({
  icon,
  title,
  meta,
  actions,
  className = "",
}: {
  icon?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={"ax-card-head" + (className ? ` ${className}` : "")}>
      {icon && <span className="ax-card-icon">{icon}</span>}
      <div className="ax-card-title">
        <span className="ax-card-title-text">{title}</span>
        {meta && <span className="ax-card-meta">{meta}</span>}
      </div>
      {actions && <div className="ax-card-actions">{actions}</div>}
    </div>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  /** Why it is empty and what to do next — never a fake placeholder row. */
  description?: ReactNode;
  action?: ReactNode;
  /** `error` switches the tone for failed loads. */
  tone?: "neutral" | "error";
  className?: string;
}

/** Honest empty state: explains the absence instead of faking content. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  tone = "neutral",
  className = "",
}: EmptyStateProps) {
  return (
    <div
      className={["ax-empty", `ax-tone-${tone}`, className].filter(Boolean).join(" ")}
      role={tone === "error" ? "alert" : undefined}
    >
      {icon && <span className="ax-empty-icon">{icon}</span>}
      <p className="ax-empty-title">{title}</p>
      {description && <p className="ax-empty-text">{description}</p>}
      {action && <div className="ax-empty-action">{action}</div>}
    </div>
  );
}

/**
 * Loading placeholder. Respects prefers-reduced-motion (the shimmer stops,
 * the block stays) via the motion tokens.
 */
export function Skeleton({
  width,
  height = 12,
  radius,
  className = "",
  count = 1,
}: {
  width?: number | string;
  height?: number;
  radius?: number;
  className?: string;
  count?: number;
}) {
  const rows = Array.from({ length: Math.max(1, count) });
  return (
    <span className={"ax-skeleton-group" + (className ? ` ${className}` : "")} aria-hidden>
      {rows.map((_, index) => (
        <span
          key={index}
          className="ax-skeleton"
          style={{
            width: typeof width === "number" ? `${width}px` : (width ?? "100%"),
            height: `${height}px`,
            borderRadius: radius != null ? `${radius}px` : undefined,
          }}
        />
      ))}
    </span>
  );
}

/** Value that is genuinely unknown. Renders an em dash, never a guess. */
export function Unknown({ title }: { title?: string }) {
  const { t } = useLocale();
  return (
    <span className="ax-unknown" title={title ?? t("ui.card.no_data")}>
      —
    </span>
  );
}
