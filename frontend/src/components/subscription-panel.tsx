"use client";

import { useTranslations } from "@/i18n/provider";
import type { SubscriptionView } from "@/lib/bots";

const STATUS_TONE: Record<SubscriptionView["status"], string> = {
  ACTIVE: "text-green-600",
  GRACE_PERIOD: "text-amber-600",
  SUSPENDED: "text-red-500",
};

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function SubscriptionPanel({ subscription }: { subscription: SubscriptionView }) {
  const t = useTranslations();

  return (
    <section className="card space-y-2">
      <h2 className="font-medium">{t("bot.subscription.title")}</h2>
      <p className={`text-sm font-medium ${STATUS_TONE[subscription.status]}`}>
        {t(`bot.subscription.status.${subscription.status}`)}
      </p>
      <p className="text-sm text-muted">
        {t("bot.subscription.monthlyAmount", { amount: subscription.monthly_amount.formatted })}
      </p>
      {subscription.status === "SUSPENDED" ? (
        <p className="text-sm text-muted">{t("bot.subscription.contactToRenew")}</p>
      ) : (
        <p className="text-sm text-muted">
          {t("bot.subscription.renewsOn", { date: formatDate(subscription.current_period_end) })}
        </p>
      )}
      {subscription.status === "GRACE_PERIOD" && subscription.grace_period_ends_at ? (
        <p className="text-sm text-amber-600">
          {t("bot.subscription.graceUntil", { date: formatDate(subscription.grace_period_ends_at) })}
        </p>
      ) : null}
    </section>
  );
}
