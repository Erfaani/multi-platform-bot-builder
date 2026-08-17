"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { botsApi, type AnalyticsSummaryView } from "@/lib/bots";

export function AnalyticsPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [summary, setSummary] = useState<AnalyticsSummaryView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    botsApi
      .analytics(botId, locale)
      .then(setSummary)
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }, [botId, locale, t]);

  if (!summary) {
    return error ? <p className="text-sm text-red-500">{error}</p> : null;
  }

  const max = Math.max(1, ...summary.daily_messages.map((point) => point.count));

  return (
    <section className="card space-y-4">
      <h2 className="font-medium">{t("bot.analytics.title")}</h2>

      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <p className="text-2xl font-semibold">{summary.total_contacts}</p>
          <p className="text-xs text-muted">{t("bot.analytics.totalContacts")}</p>
        </div>
        <div>
          <p className="text-2xl font-semibold">{summary.new_contacts_7d}</p>
          <p className="text-xs text-muted">{t("bot.analytics.newContacts")}</p>
        </div>
        <div>
          <p className="text-2xl font-semibold">{summary.messages_7d}</p>
          <p className="text-xs text-muted">{t("bot.analytics.messages7d")}</p>
        </div>
      </div>

      <div>
        <p className="pb-2 text-xs text-muted">{t("bot.analytics.dailyMessages")}</p>
        <div className="flex h-16 items-end gap-1">
          {summary.daily_messages.map((point) => (
            <div
              key={point.date}
              title={`${point.date}: ${point.count}`}
              className="flex-1 rounded-sm bg-accent/70"
              style={{ height: `${Math.max(4, (point.count / max) * 100)}%` }}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
