"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { botsApi, type AvailableFeatureView } from "@/lib/bots";
import { checkoutApi } from "@/lib/checkout";

export function AddonFeaturesPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();

  const [features, setFeatures] = useState<AvailableFeatureView[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    botsApi
      .availableFeatures(botId, locale)
      .then(setFeatures)
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }, [botId, locale, t]);

  function toggle(slug: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  async function buy() {
    if (selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const quote = await botsApi.addonQuote(botId, [...selected], locale);
      const order = await checkoutApi.placeOrder(quote.id, locale);
      router.push(`/${locale}/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
      setBusy(false);
    }
  }

  if (features.length === 0 && !error) return null;

  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{t("bot.addFeatures.title")}</h2>
      <p className="text-sm text-muted">{t("bot.addFeatures.hint")}</p>

      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <ul className="space-y-2">
        {features.map((feature) => (
          <li key={feature.slug}>
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-line p-3 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={selected.has(feature.slug)}
                onChange={() => toggle(feature.slug)}
              />
              <span className="flex-1">
                <span className="block font-medium">{feature.name}</span>
                <span className="block text-muted">{feature.description}</span>
              </span>
              <span className="shrink-0 text-end text-xs text-muted">
                <span className="block">{feature.setup_amount.formatted}</span>
                {feature.monthly_amount.amount_minor > 0 ? (
                  <span className="block">
                    +{feature.monthly_amount.formatted}/{t("builder.price.monthly")}
                  </span>
                ) : null}
              </span>
            </label>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={buy}
        disabled={busy || selected.size === 0}
        className="btn-primary"
      >
        {busy ? t("common.loading") : t("bot.addFeatures.buy")}
      </button>
    </section>
  );
}
