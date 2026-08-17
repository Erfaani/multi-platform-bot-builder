"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { OrderStatusBadge } from "@/components/order-status";
import { useIntl, useTranslations } from "@/i18n/provider";
import { useAuth } from "@/lib/auth";
import { checkoutApi, type OrderSummary } from "@/lib/checkout";

export default function OrdersPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const { user, loading, activeTenantId } = useAuth();

  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    checkoutApi
      .orders(locale)
      .then((page) => setOrders(page.results))
      .catch(() => setFailed(true));
  }, [locale]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user) load();
  }, [user, activeTenantId, load]);

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("orders.title")}</h1>

      {failed ? <p className="text-sm text-red-500">{t("error.network")}</p> : null}

      {orders.length === 0 ? (
        <div className="card space-y-3">
          <p className="text-sm text-muted">{t("orders.empty")}</p>
          <Link href={`/${locale}/build`} className="btn-primary inline-flex">
            {t("home.cta.primary")}
          </Link>
        </div>
      ) : (
        <ul className="space-y-2">
          {orders.map((order) => (
            <li key={order.id}>
              <Link
                href={`/${locale}/orders/${order.id}`}
                className="card flex items-center justify-between gap-3 transition hover:border-accent"
              >
                <span>
                  <span className="block text-sm font-medium">#{order.number}</span>
                  <span className="block text-xs text-muted">
                    {new Date(order.created_at).toLocaleDateString(
                      locale === "fa" ? "fa-IR" : "en-US",
                    )}
                  </span>
                </span>
                <span className="flex items-center gap-3">
                  <span className="text-sm">{order.total.formatted}</span>
                  <OrderStatusBadge status={order.status} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
