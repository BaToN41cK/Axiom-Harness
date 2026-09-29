/**
 * Platform helpers. macOS uses ⌘ where Windows/Linux use Ctrl, and the shell
 * has to render the right modifier in tooltips, menus and the palette.
 */

/** True on macOS (Tauri webview reports the host platform in the UA). */
export const IS_MAC =
  typeof navigator !== "undefined" &&
  /mac/i.test(navigator.platform || navigator.userAgent || "");

/** "Ctrl" / "⌘" for the primary modifier. */
export const MOD_LABEL = IS_MAC ? "⌘" : "Ctrl";
/** "Alt" / "⌥". */
export const ALT_LABEL = IS_MAC ? "⌥" : "Alt";
/** "Shift" / "⇧". */
export const SHIFT_LABEL = IS_MAC ? "⇧" : "Shift";

/**
 * Normalise a shortcut written with the `Mod` placeholder into the labels of
 * the current platform: `Mod+Shift+F` → `Ctrl+Shift+F` / `⌘⇧F`.
 */
export function shortcutLabel(spec: string): string {
  const parts = spec.split("+").map((part) => {
    const key = part.trim();
    const lower = key.toLowerCase();
    if (lower === "mod" || lower === "ctrl" || lower === "cmd") return MOD_LABEL;
    if (lower === "alt" || lower === "option") return ALT_LABEL;
    if (lower === "shift") return SHIFT_LABEL;
    if (lower === "enter") return "Enter";
    if (lower === "esc" || lower === "escape") return "Esc";
    return key.length === 1 ? key.toUpperCase() : key;
  });
  return IS_MAC ? parts.join("") : parts.join("+");
}

/** True when the event carries the platform's primary modifier. */
export function hasMod(event: Pick<KeyboardEvent, "ctrlKey" | "metaKey">): boolean {
  return IS_MAC ? event.metaKey : event.ctrlKey;
}
