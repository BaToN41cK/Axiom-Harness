import { useCallback, useEffect, useRef } from "react";

interface SplitterProps {
  /** Which edge the handle belongs to; decides the drag direction. */
  side: "left" | "right";
  /** Current size in px, owned by the caller. */
  value: number;
  min: number;
  max: number;
  /** Size restored on double click. */
  defaultValue: number;
  /** Live updates while dragging. */
  onChange: (value: number) => void;
  /** Called once on release / reset so the caller can persist the size. */
  onCommit: (value: number) => void;
  label: string;
}

/**
 * Drag handle for resizable panels. Also a real slider for the keyboard:
 * arrows nudge by 16px, Home/End jump to the limits, double click resets.
 */
export function Splitter({
  side,
  value,
  min,
  max,
  defaultValue,
  onChange,
  onCommit,
  label,
}: SplitterProps) {
  const dragging = useRef(false);
  const latest = useRef(value);
  latest.current = value;

  const clamp = useCallback(
    (next: number) => Math.min(max, Math.max(min, Math.round(next))),
    [max, min],
  );

  useEffect(() => {
    const onMove = (event: MouseEvent) => {
      if (!dragging.current) return;
      const next = clamp(side === "left" ? event.clientX : window.innerWidth - event.clientX);
      latest.current = next;
      onChange(next);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.classList.remove("resizing");
      onCommit(latest.current);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [clamp, onChange, onCommit, side]);

  const nudge = (delta: number) => {
    const next = clamp(value + delta);
    onChange(next);
    onCommit(next);
  };

  return (
    <div
      className={"ax-splitter ax-splitter-" + side}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onMouseDown={() => {
        dragging.current = true;
        document.body.classList.add("resizing");
      }}
      onDoubleClick={() => {
        onChange(defaultValue);
        onCommit(defaultValue);
      }}
      onKeyDown={(event) => {
        const outward = side === "left" ? 16 : -16;
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          nudge(side === "left" ? -16 : 16);
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          nudge(outward);
        } else if (event.key === "Home") {
          event.preventDefault();
          nudge(min - value);
        } else if (event.key === "End") {
          event.preventDefault();
          nudge(max - value);
        } else if (event.key === "Enter") {
          event.preventDefault();
          onChange(defaultValue);
          onCommit(defaultValue);
        }
      }}
    />
  );
}
