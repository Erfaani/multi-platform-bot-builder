"use client";

import { useTranslations } from "@/i18n/provider";
import type { QuoteView } from "@/lib/builder";

export function PriceSummary({
  quote,
  busy,
}: {
  quote: QuoteView | null;
  busy?: boolean;
}) {
  const t = useTranslations();

  if (!quote) {
    return (
      <aside className="card space-y-2">
        <h3 className="font-medium">{t("builder.price.title")}</h3>
        <p className="text-sm text-muted">{t("builder.price.empty")}</p>
      </aside>
    );
  }

  const once = quote.items.filter((item) => item.billing_kind === "ONE_TIME");
  const monthly = quote.items.filter((item) => item.billing_kind === "RECURRING_MONTHLY");

  return (
    <aside className={`card space-y-4 ${busy ? "opacity-60" : ""}`}>
      <h3 className="font-medium">{t("builder.price.title")}</h3>

      {once.length > 0 ? (
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted">
            {t("builder.price.oneTime")}
          </p>
          {once.map((item) => (
            <div key={item.price_key} className="flex justify-between gap-3 text-sm">
              <span className="text-muted">
                {item.label}
                {item.quantity > 1 ? ` ×${item.quantity}` : ""}
              </span>
              <span>{item.amount.formatted}</span>
            </div>
          ))}
        </div>
      ) : null}

      {monthly.length > 0 ? (
        <div className="space-y-1 border-t border-line pt-3">
          <p className="text-xs uppercase tracking-wide text-muted">
            {t("builder.price.monthly")}
          </p>
          {monthly.map((item) => (
            <div key={item.price_key} className="flex justify-between gap-3 text-sm">
              <span className="text-muted">{item.label}</span>
              <span>{item.amount.formatted}</span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="space-y-1 border-t border-line pt-3">
        <div className="flex justify-between gap-3 text-sm text-muted">
          <span>{t("builder.price.setupTotal")}</span>
          <span>{quote.subtotal_once.formatted}</span>
        </div>
        <div className="flex justify-between gap-3 text-sm text-muted">
          <span>{t("builder.price.monthlyTotal")}</span>
          <span>{quote.subtotal_recurring.formatted}</span>
        </div>
        <div className="flex justify-between gap-3 pt-1 font-medium">
          <span>{t("builder.price.dueNow")}</span>
          <span>{quote.total.formatted}</span>
        </div>
      </div>

      <p className="text-xs text-muted">{t("builder.price.note")}</p>
    </aside>
  );
}
