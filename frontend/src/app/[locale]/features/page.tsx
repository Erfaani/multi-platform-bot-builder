"use client";

import { useEffect, useMemo, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { builderApi, type FeatureItem } from "@/lib/builder";

export default function FeaturesPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const [features, setFeatures] = useState<FeatureItem[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    builderApi
      .features(locale)
      .then(setFeatures)
      .catch(() => setFailed(true));
  }, [locale]);

  const byCategory = useMemo(() => {
    const groups = new Map<string, FeatureItem[]>();
    for (const feature of features) {
      const list = groups.get(feature.category) ?? [];
      list.push(feature);
      groups.set(feature.category, list);
    }
    return [...groups.entries()];
  }, [features]);

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t("features.title")}</h1>
        <p className="text-muted">{t("features.subtitle")}</p>
      </header>

      {failed ? <p className="text-sm text-red-500">{t("error.network")}</p> : null}

      {byCategory.map(([category, items]) => (
        <section key={category} className="space-y-3">
          <h2 className="text-sm uppercase tracking-wide text-muted">
            {t(`features.category.${category}`)}
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {items.map((feature) => (
              <article key={feature.slug} className="card space-y-1">
                <h3 className="text-sm font-medium">{feature.name}</h3>
                <p className="text-xs text-muted">{feature.description}</p>
                <p className="text-xs text-muted">
                  {Object.entries(feature.platforms)
                    .map(
                      ([platform, info]) =>
                        `${platform}: ${info.available ? "✓" : "✕"}`,
                    )
                    .join(" · ")}
                </p>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
