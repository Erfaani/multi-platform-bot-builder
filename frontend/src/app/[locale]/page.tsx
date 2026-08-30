"use client";

import Link from "next/link";
import { useIntl, useTranslations } from "@/i18n/provider";

export default function HomePage() {
  const t = useTranslations();
  const { locale } = useIntl();

  const points = [
    "home.point.hosting",
    "home.point.platforms",
    "home.point.features",
    "home.point.dashboard",
  ];

  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <h1 className="text-3xl font-semibold leading-tight sm:text-4xl">{t("home.title")}</h1>
        <p className="max-w-2xl text-muted">{t("home.subtitle")}</p>

        <div className="flex flex-wrap gap-3 pt-2">
          <Link href={`/${locale}/build`} className="btn-primary">
            {t("home.cta.primary")}
          </Link>
          <Link href={`/${locale}/templates`} className="btn-ghost">
            {t("home.cta.secondary")}
          </Link>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        {points.map((key) => (
          <div key={key} className="card">
            <p className="text-sm">{t(key)}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
