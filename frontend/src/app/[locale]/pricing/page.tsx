"use client";

import Link from "next/link";
import { useIntl, useTranslations } from "@/i18n/provider";

const POINTS = ["modular", "onceOnly", "multiPlatform", "hosting", "currency"] as const;

export default function PricingPage() {
  const t = useTranslations();
  const { locale } = useIntl();

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t("pricing.title")}</h1>
        <p className="text-muted">{t("pricing.subtitle")}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        {POINTS.map((point) => (
          <article key={point} className="card space-y-1">
            <h2 className="text-sm font-medium">{t(`pricing.point.${point}.title`)}</h2>
            <p className="text-xs text-muted">{t(`pricing.point.${point}.body`)}</p>
          </article>
        ))}
      </div>

      <p className="rounded-lg border border-line p-4 text-sm text-muted">
        {t("pricing.calculator")}
      </p>

      <Link href={`/${locale}/build`} className="btn-primary inline-flex">
        {t("pricing.cta")}
      </Link>
    </div>
  );
}
