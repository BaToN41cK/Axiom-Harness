"""Regenerate ``desktop/src/lib/i18n.ts`` from the core catalog.

The core ``src/axiom/core/i18n.py`` ``TRANSLATIONS`` dict is the single source of
truth. This script emits the Desktop snapshot (``I18N_KEYS`` + ``FALLBACK_STRINGS``)
so the two render paths never drift. Run it whenever the catalog changes:

    python desktop/scripts/gen_i18n.py

The helper functions below are stable and are emitted verbatim; only the data
tables are regenerated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from axiom.core.i18n import TRANSLATIONS  # noqa: E402

# Only the Desktop-rendered ``ui.*`` keys are part of the snapshot; the core-only
# keys (task.*, permission.*, autonomy.*) are consumed by the core/TUI.
UI_KEYS = [key for key in TRANSLATIONS if key.startswith("ui.")]

HELPERS = '''\
export function normalizeLocale(value: unknown): AppLocale {
  return value === "ru" ? "ru" : "en";
}

/** Same fallback semantics as core `translate`: unknown key renders as the key. */
export function t(
  key: string,
  locale: unknown,
  strings?: Record<string, string> | null,
): string {
  const hit = strings?.[key];
  if (typeof hit === "string" && hit.length > 0) return hit;
  const loc = normalizeLocale(locale);
  const snap = (FALLBACK_STRINGS[loc] as Record<string, string>)[key];
  if (typeof snap === "string") return snap;
  return key;
}

/** `t()` plus `{var}` interpolation (core `translate` supports kwargs too). */
export function tVar(
  key: string,
  locale: unknown,
  strings: Record<string, string> | null | undefined,
  vars: Record<string, string>,
): string {
  let out = t(key, locale, strings);
  for (const [name, value] of Object.entries(vars)) {
    out = out.split(`{${name}}`).join(value);
  }
  return out;
}

/**
 * one/few/many plural pick. Russian keeps three forms, English folds
 * few/many into `other` — callers pass the resolved `one`/`few`/`many`
 * keys and this returns the rendered string for `n`.
 */
export function pluralKey(n: number, locale: unknown): string {
  if (normalizeLocale(locale) !== "ru") return n === 1 ? "one" : "other";
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "one";
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "few";
  return "many";
}

/** Render `{n} <noun>` with locale plural rules over `base.one/few/many`. */
export function plural(
  base: string,
  n: number,
  locale: unknown,
  strings?: Record<string, string> | null,
): string {
  const form = pluralKey(n, locale) === "other" ? "few" : pluralKey(n, locale);
  return tVar(`${base}.${form}`, locale, strings, { n: String(n) });
}

export interface I18nReply {
  locale: AppLocale;
  locales: string[];
  strings: Record<string, string>;
}

/** Fetch the core catalog over the bridge; returns null when the core is unreachable. */
export async function fetchI18n(
  doRequest: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>,
  locale?: string,
): Promise<I18nReply | null> {
  try {
    const reply = await doRequest<I18nReply>("i18n", locale ? { locale } : {});
    if (!reply || typeof reply.strings !== "object") return null;
    return { locale: normalizeLocale(reply.locale), locales: reply.locales ?? ["en", "ru"], strings: reply.strings };
  } catch {
    return null;
  }
}
'''

HEADER = '''\
/**
 * W3.8 i18n projection (Desktop renderer).
 *
 * Single source of truth is the core `TRANSLATIONS` catalog
 * (`src/axiom/core/i18n.py`), served over the `i18n` bridge command.
 * This file is REGENERATED from the core catalog by
 * `desktop/scripts/gen_i18n.py` — do not hand-edit the tables below;
 * add keys in core and re-run the generator.
 * `t()` reads the fetched dict and falls back to the key itself
 * (same semantics as core `translate`); `FALLBACK_STRINGS` is only a
 * boot snapshot used before the first bridge reply arrives.
 */

export type AppLocale = "en" | "ru";

'''


def _j(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def key_lines() -> str:
    lines = ["export const I18N_KEYS = ["]
    for key in UI_KEYS:
        lines.append(f'  {_j(key)},')
    lines.append("] as const;")
    lines.append("")
    lines.append("export type I18nKey = (typeof I18N_KEYS)[number];")
    lines.append("")
    return "\n".join(lines)


def fallback_lines() -> str:
    lines = [
        "/** Boot snapshot — regenerated from core TRANSLATIONS. */",
        "export const FALLBACK_STRINGS: Record<AppLocale, Record<I18nKey, string>> = {",
    ]
    for locale in ("en", "ru"):
        lines.append(f"  {locale}: {{")
        for key in UI_KEYS:
            lines.append(f"    {_j(key)}: {_j(TRANSLATIONS[key][locale])},")
        lines.append("  },")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    out = HEADER + key_lines() + fallback_lines() + HELPERS
    target = REPO / "desktop" / "src" / "lib" / "i18n.ts"
    target.write_text(out, encoding="utf-8")
    print(f"Wrote {target} ({len(UI_KEYS)} ui.* keys)")


if __name__ == "__main__":
    main()
