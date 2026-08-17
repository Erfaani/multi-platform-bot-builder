"use client";

import Link from "next/link";
import { useIntl, useTranslations } from "@/i18n/provider";

const STEPS = ["configure", "price", "preview", "pay", "provision", "manage"] as const;

export default function HowItWorksPage() {
  const t = useTranslations();
  const { locale } = useIntl();

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t("how.title")}</h1>
        <p className="text-muted">{t("how.subtitle")}</p>
      </header>

      <ol className="space-y-4">
        {STEPS.map((step, index) => (
          <li key={step} className="card flex gap-4">
            <span className="text-lg font-semibold text-accent">{index + 1}</span>
            <span>
              <span className="block font-medium">{t(`how.step.${step}.title`)}</span>
              <span className="block text-sm text-muted">{t(`how.step.${step}.body`)}</span>
            </span>
          </li>
        ))}
      </ol>

      <Link href={`/${locale}/build`} className="btn-primary inline-flex">
        {t("home.cta.primary")}
      </Link>
    </div>
  );
}
