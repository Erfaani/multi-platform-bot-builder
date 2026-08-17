"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { OrderProgress, OrderStatusBadge } from "@/components/order-status";
import { PaymentPanel } from "@/components/payment-panel";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { checkoutApi, type OrderView } from "@/lib/checkout";

export default function OrderDetailPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const { user, loading } = useAuth();

  const [order, setOrder] = useState<OrderView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!params?.id) return;
    checkoutApi
      .order(params.id, locale)
      .then(setOrder)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : t("error.network")),
      );
  }, [params?.id, locale, t]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function cancel() {
    if (!order) return;
    try {
      setOrder(await checkoutApi.cancelOrder(order.id, "", locale));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;
  if (error && !order) return <p className="text-sm text-red-500">{error}</p>;
  if (!order) return <p className="text-muted">{t("common.loading")}</p>;

  const once = order.items.filter((item) => item.billing_kind === "ONE_TIME");
  const monthly = order.items.filter((item) => item.billing_kind === "RECURRING_MONTHLY");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href={`/${locale}/orders`} className="text-xs text-muted hover:text-ink">
            ← {t("orders.title")}
          </Link>
          <h1 className="text-2xl font-semibold">
            {t("order.number", { number: order.number })}
          </h1>
        </div>
        <OrderStatusBadge status={order.status} />
      </div>

      <OrderProgress status={order.status} />

      {error ? (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      ) : null}

      <PaymentPanel order={order} onChanged={load} />

      <section className="card space-y-3">
        <h2 className="font-medium">{t("order.summary")}</h2>
        <p className="text-sm text-muted">
          {order.platforms.join(" + ")} · {order.template}
        </p>

        <div className="space-y-1">
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

        {monthly.length > 0 ? (
          <div className="space-y-1 border-t border-line pt-2">
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

        {order.discount.amount_minor > 0 ? (
          <div className="flex justify-between gap-3 border-t border-line pt-2 text-sm text-green-600">
            <span>{t("order.discount")}</span>
            <span>−{order.discount.formatted}</span>
          </div>
        ) : null}

        <div className="flex justify-between gap-3 border-t border-line pt-2 font-medium">
          <span>{t("builder.price.dueNow")}</span>
          <span>{order.total.formatted}</span>
        </div>
      </section>

      <section className="card space-y-2">
        <h2 className="font-medium">{t("order.history")}</h2>
        <ul className="space-y-1 text-xs text-muted">
          {order.events.map((event, index) => (
            <li key={index} className="flex justify-between gap-3">
              <span>
                {t(`order.status.${event.to_status}`)}
                {event.reason ? ` — ${event.reason}` : ""}
              </span>
              <span>
                {new Date(event.created_at).toLocaleString(
                  locale === "fa" ? "fa-IR" : "en-US",
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {order.available_actions.includes("CANCELLED") ? (
        <button type="button" onClick={cancel} className="btn-ghost">
          {t("order.cancel")}
        </button>
      ) : null}
    </div>
  );
}
