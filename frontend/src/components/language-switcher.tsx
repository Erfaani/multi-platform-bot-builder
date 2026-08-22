"use client";

import { usePathname, useRouter } from "next/navigation";
import { LOCALES, type Locale } from "@/i18n/config";
import { useIntl } from "@/i18n/provider";
import { api, tokenStore } from "@/lib/api";

const LABELS: Record<Locale, string> = { en: "English", fa: "فارسی" };

export function LanguageSwitcher() {
  const { locale } = useIntl();
  const pathname = usePathname();
  const router = useRouter();

  async function switchTo(next: Locale) {
    if (next === locale) return;

    // Persist for a year so the choice survives across devices sessions,
    // and on the profile so bots and emails honour it too (I18N.md §2).
    document.cookie = `locale=${next}; path=/; max-age=31536000; samesite=lax`;
    if (tokenStore.access) {
      try {
        await api.updateMe({ preferred_locale: next });
      } catch {
        // A failed preference save must not block the language change.
      }
    }

    const segments = pathname.split("/");
    segments[1] = next;
    router.push(segments.join("/") || `/${next}`);
    router.refresh();
  }

  return (
    <div className="flex items-center gap-1 rounded-full bg-white/10 p-1">
      {LOCALES.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => void switchTo(option)}
          aria-current={option === locale ? "true" : undefined}
          className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
            option === locale ? "bg-accent text-white" : "text-white/70 hover:text-white"
          }`}
        >
          {LABELS[option]}
        </button>
      ))}
    </div>
  );
}
