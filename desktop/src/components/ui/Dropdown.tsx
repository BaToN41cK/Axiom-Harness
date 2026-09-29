import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

export interface MenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  /** Right-aligned hint: shortcut or a short state note. */
  hint?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

interface DropdownProps {
  /** The control that opens the menu; receives the aria wiring. */
  trigger: (props: {
    open: boolean;
    toggle: () => void;
    ref: React.Ref<HTMLButtonElement>;
    "aria-expanded": boolean;
    "aria-haspopup": "menu";
  }) => ReactNode;
  items: MenuItem[];
  label: string;
  align?: "start" | "end";
  className?: string;
  /** Optional header row inside the menu. */
  title?: string;
}

/**
 * Accessible dropdown menu: click outside or Escape closes it, arrows move the
 * cursor, Enter activates. Focus returns to the trigger on close.
 */
export function Dropdown({ trigger, items, label, align = "start", className = "", title }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const hostRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const close = useCallback((focusTrigger = true) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!hostRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setCursor(items.findIndex((item) => !item.disabled));
      menuRef.current?.focus();
    }
  }, [open, items]);

  const step = (delta: number) => {
    const usable = items.filter((item) => !item.disabled);
    if (usable.length === 0) return;
    let next = cursor;
    for (let i = 0; i < items.length; i += 1) {
      next = (next + delta + items.length) % items.length;
      if (!items[next].disabled) break;
    }
    setCursor(next);
  };

  return (
    <div ref={hostRef} className={"ax-dropdown" + (className ? ` ${className}` : "")}>
      {trigger({
        open,
        toggle: () => setOpen((value) => !value),
        ref: triggerRef,
        "aria-expanded": open,
        "aria-haspopup": "menu",
      })}
      {open && (
        <div
          ref={menuRef}
          className={"ax-menu ax-menu-" + align}
          role="menu"
          aria-label={label}
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              close();
            } else if (event.key === "ArrowDown") {
              event.preventDefault();
              step(1);
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              step(-1);
            } else if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              const item = items[cursor];
              if (item && !item.disabled) {
                close();
                item.onSelect();
              }
            } else if (event.key === "Tab") {
              close(false);
            }
          }}
        >
          {title && <p className="ax-menu-title">{title}</p>}
          {items.map((item, index) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              className={
                "ax-menu-item" +
                (item.danger ? " is-danger" : "") +
                (index === cursor ? " is-cursor" : "")
              }
              onMouseEnter={() => setCursor(index)}
              onClick={() => {
                close();
                item.onSelect();
              }}
            >
              {item.icon && <span className="ax-menu-icon">{item.icon}</span>}
              <span className="ax-menu-label">{item.label}</span>
              {item.hint && <span className="ax-menu-hint">{item.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
