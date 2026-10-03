/**
 * W3.8 locale context (Desktop renderer).
 *
 * `LocaleProvider` sits near the root of `App` and follows `Config.locale`.
 * Any presentational component reads `{ locale, strings, t }` via `useLocale()`
 * — no prop drilling, no whole-store subscription. The strings themselves come
 * from the core `TRANSLATIONS` catalog over the `i18n` bridge command; before
 * the first reply arrives `t` serves the embedded snapshot from `lib/i18n`
 * (identical values, drift-covered by `tests/core/test_i18n.py`).
 */
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { fetchI18n, normalizeLocale, t as translate, tVar } from "./i18n";
import type { AppLocale } from "./i18n";
import { request } from "../bridge";

export interface LocaleShape {
  locale: AppLocale;
  strings: Record<string, string> | null;
  /** Bound translate: `t(key)` / `t(key, vars)`. */
  t: (key: string, vars?: Record<string, string>) => string;
}

const LocaleContext = createContext<LocaleShape>({
  locale: "ru",
  strings: null,
  t: (key: string) => translate(key, "ru", null),
});

export function LocaleProvider({ locale: raw, children }: { locale: unknown; children: ReactNode }) {
  const locale = normalizeLocale(raw);
  const [strings, setStrings] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    let live = true;
    setStrings(null);
    void fetchI18n(request, locale).then((reply) => {
      if (live && reply) setStrings(reply.strings);
    });
    return () => {
      live = false;
    };
  }, [locale]);
  const t = useCallback(
    (key: string, vars?: Record<string, string>) =>
      vars ? tVar(key, locale, strings, vars) : translate(key, locale, strings),
    [locale, strings],
  );
  return <LocaleContext.Provider value={{ locale, strings, t }}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleShape {
  return useContext(LocaleContext);
}
