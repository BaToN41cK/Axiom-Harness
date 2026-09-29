import type { ReactNode } from "react";
import { shortcutLabel } from "../../lib/platform";

/**
 * Shortcut hint. Accepts the platform-neutral `Mod+K` form and renders
 * `Ctrl+K` or `⌘K` depending on the host.
 */
export function Kbd({ keys, className = "" }: { keys: string; className?: string }) {
  return <kbd className={"ax-kbd" + (className ? ` ${className}` : "")}>{shortcutLabel(keys)}</kbd>;
}

interface TooltipProps {
  /** Tooltip text. Kept short; long help belongs in the UI itself. */
  content: string;
  /** Optional shortcut appended to the tooltip in `Mod+K` form. */
  shortcut?: string;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactNode;
  className?: string;
}

/**
 * CSS-only tooltip: shows on hover and on keyboard focus, and mirrors the text
 * into `aria-label` on the wrapper so assistive tech gets the same string
 * without a live region.
 */
export function Tooltip({ content, shortcut, side = "top", children, className = "" }: TooltipProps) {
  const text = shortcut ? `${content} · ${shortcutLabel(shortcut)}` : content;
  return (
    <span
      className={["ax-tooltip-host", `ax-tooltip-${side}`, className].filter(Boolean).join(" ")}
      data-tooltip={text}
    >
      {children}
      <span className="ax-tooltip" role="tooltip">
        {content}
        {shortcut && <Kbd keys={shortcut} />}
      </span>
    </span>
  );
}
