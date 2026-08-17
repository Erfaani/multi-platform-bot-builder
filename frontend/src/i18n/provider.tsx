"use client";

import { createContext, useCallback, useContext, useMemo } from "react";
import type { Locale } from "./config";
import { directionOf } from "./config";

type Messages = Record<string, string>;

interface IntlValue {
  locale: Locale;
  dir: "rtl" | "ltr";
  t: (key: string, params?: Record<string, string | number>) => string;
}

const IntlContext = createContext<IntlValue | null>(null);

export function IntlProvider({
  locale,
  messages,
  children,
}: {
  locale: Locale;
  messages: Messages;
  children: React.ReactNode;
}) {
  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      // Falling back to the key makes a missing translation obvious in review
      // rather than rendering an empty element (I18N.md §6).
      const template = messages[key] ?? key;
      if (!params) return template;
      return template.replace(/\{(\w+)\}/g, (match, name) =>
        name in params ? String(params[name]) : match,
      );
    },
    [messages],
  );

  const value = useMemo<IntlValue>(
    () => ({ locale, dir: directionOf(locale), t }),
    [locale, t],
  );

  return <IntlContext.Provider value={value}>{children}</IntlContext.Provider>;
}

export function useIntl(): IntlValue {
  const context = useContext(IntlContext);
  if (!context) throw new Error("useIntl must be used inside IntlProvider.");
  return context;
}

export function useTranslations() {
  return useIntl().t;
}
