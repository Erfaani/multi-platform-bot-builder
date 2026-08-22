"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { builderApi, type BusinessTemplate } from "@/lib/builder";
import { AppIcon } from "@/lib/icons";

export default function TemplatesPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const [templates, setTemplates] = useState<BusinessTemplate[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    builderApi
      .templates(locale)
      .then(setTemplates)
      .catch(() => setFailed(true));
  }, [locale]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t("templates.title")}</h1>
        <p className="text-muted">{t("templates.subtitle")}</p>
      </header>

      {failed ? <p className="text-sm text-red-500">{t("error.network")}</p> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        {templates.map((template) => (
          <article key={template.slug} className="card space-y-2">
            <span className="icon-badge bg-accent-soft text-accent">
              <AppIcon name={template.icon} size={20} />
            </span>
            <h2 className="font-medium">{template.name}</h2>
            <p className="text-sm text-muted">{template.description}</p>
            <p className="text-xs text-muted">
              {t("templates.featureCount", { count: template.features.length })}
            </p>
            <Link href={`/${locale}/build`} className="btn-ghost inline-flex text-sm">
              {t("home.cta.primary")}
            </Link>
          </article>
        ))}
      </div>
    </div>
  );
}
