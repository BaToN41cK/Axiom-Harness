import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/** Retain only outgoing chrome; data and chat updates are never deferred. */
export default function Presence({ open, children }: { open: boolean; children: ReactNode }) {
  const [retained, setRetained] = useState(open);
  const last = useRef<ReactNode>(children);
  const host = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (host.current) host.current.inert = !open;
    if (open) last.current = children;
  }, [open, children]);

  useLayoutEffect(() => {
    if (open) {
      setRetained(true);
      return;
    }
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const check = () => {
      if (media.matches || document.documentElement.classList.contains("no-anim")) setRetained(false);
    };
    check();
    const timer = window.setTimeout(() => setRetained(false), 180);
    const observer = new MutationObserver(check);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    media.addEventListener("change", check);
    return () => {
      window.clearTimeout(timer);
      observer.disconnect();
      media.removeEventListener("change", check);
    };
  }, [open]);

  if (!open && !retained) return null;
  return (
    <div ref={host} className="presence" data-state={open ? "open" : "closed"} aria-hidden={!open || undefined}>
      {open ? children : last.current}
    </div>
  );
}