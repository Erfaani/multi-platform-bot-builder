"use client";

import { useTranslations } from "@/i18n/provider";

const QUESTIONS = [
  "hosting",
  "token",
  "platforms",
  "changeLater",
  "payment",
  "howLong",
] as const;

export default function FaqPage() {
  const t = useTranslations();

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t("faq.title")}</h1>
        <p className="text-muted">{t("faq.subtitle")}</p>
      </header>

      <dl className="space-y-3">
        {QUESTIONS.map((key) => (
          <div key={key} className="card space-y-1">
            <dt className="text-sm font-medium">{t(`faq.q.${key}.q`)}</dt>
            <dd className="text-sm text-muted">{t(`faq.q.${key}.a`)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
