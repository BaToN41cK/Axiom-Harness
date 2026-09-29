import type { ReactNode } from "react";
import { Badge } from "./Status";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  icon?: ReactNode;
  /** Optional count rendered as a quiet badge (files changed, sessions...). */
  count?: number;
  disabled?: boolean;
}

interface TabsProps<T extends string> {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Accessible name of the tablist. */
  label: string;
  /** `panel` for the side panel strip, `inline` for compact segmented tabs. */
  variant?: "panel" | "inline";
  className?: string;
  /** Rendered at the trailing edge of the strip (refresh, add...). */
  actions?: ReactNode;
}

/**
 * Keyboard-accessible tab strip: arrows move between tabs, Home/End jump to
 * the ends, and the active tab is marked by accent + `aria-selected`.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  variant = "panel",
  className = "",
  actions,
}: TabsProps<T>) {
  const enabled = items.filter((item) => !item.disabled);
  const move = (delta: number) => {
    if (enabled.length === 0) return;
    const current = enabled.findIndex((item) => item.id === value);
    const next = enabled[(current + delta + enabled.length) % enabled.length];
    if (next) onChange(next.id);
  };
  return (
    <div className={["ax-tabs", `ax-tabs-${variant}`, className].filter(Boolean).join(" ")}>
      <div
        className="ax-tabs-strip"
        role="tablist"
        aria-label={label}
        onKeyDown={(event) => {
          if (event.key === "ArrowRight" || event.key === "ArrowDown") {
            event.preventDefault();
            move(1);
          } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
            event.preventDefault();
            move(-1);
          } else if (event.key === "Home") {
            event.preventDefault();
            if (enabled[0]) onChange(enabled[0].id);
          } else if (event.key === "End") {
            event.preventDefault();
            const last = enabled[enabled.length - 1];
            if (last) onChange(last.id);
          }
        }}
      >
        {items.map((item) => {
          const active = item.id === value;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`ax-tab-${item.id}`}
              aria-selected={active}
              aria-controls={`ax-tabpanel-${item.id}`}
              tabIndex={active ? 0 : -1}
              disabled={item.disabled}
              className={"ax-tab" + (active ? " is-active" : "")}
              onClick={() => onChange(item.id)}
            >
              {item.icon}
              <span className="ax-tab-label">{item.label}</span>
              {item.count != null && item.count > 0 && (
                <Badge count tone={active ? "accent" : "neutral"}>
                  {item.count}
                </Badge>
              )}
            </button>
          );
        })}
      </div>
      {actions && <div className="ax-tabs-actions">{actions}</div>}
    </div>
  );
}

/** Panel body bound to a tab; keeps the aria wiring in one place. */
export function TabPanel({
  id,
  children,
  className = "",
}: {
  id: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="tabpanel"
      id={`ax-tabpanel-${id}`}
      aria-labelledby={`ax-tab-${id}`}
      className={"ax-tabpanel" + (className ? ` ${className}` : "")}
    >
      {children}
    </div>
  );
}
