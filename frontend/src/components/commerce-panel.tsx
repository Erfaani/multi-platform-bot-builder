"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { commerceApi, type BusinessOrderView, type ProductView, type TableReservationView } from "@/lib/commerce";

export function CommercePanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [products, setProducts] = useState<ProductView[]>([]);
  const [orders, setOrders] = useState<BusinessOrderView[]>([]);
  const [reservations, setReservations] = useState<TableReservationView[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    commerceApi.products(botId, locale).then(setProducts).catch(() => setError(t("error.network")));
    commerceApi.orders(botId, locale).then(setOrders).catch(() => {});
    commerceApi.reservations(botId, locale).then(setReservations).catch(() => {});
  }

  useEffect(load, [botId, locale, t]);

  async function addProduct(event: React.FormEvent) {
    event.preventDefault();
    const priceMinor = Math.round(Number(price) * 100);
    if (!name.trim() || !Number.isFinite(priceMinor) || priceMinor < 0) return;

    setBusy(true);
    setError(null);
    try {
      await commerceApi.createProduct(botId, { name, price_minor: priceMinor }, locale);
      setName("");
      setPrice("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function removeProduct(productId: number) {
    try {
      await commerceApi.deleteProduct(botId, productId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function cancelOrder(orderId: string) {
    try {
      await commerceApi.cancelOrder(botId, orderId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function cancelReservation(reservationId: string) {
    try {
      await commerceApi.cancelReservation(botId, reservationId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  const activeOrders = orders.filter((o) => o.status === "CONFIRMED" || o.status === "PENDING");
  const activeReservations = reservations.filter((r) => r.status === "CONFIRMED");

  return (
    <section className="card space-y-5">
      <h2 className="font-medium">{t("bot.commerce.title")}</h2>
      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-muted">{t("bot.commerce.products")}</h3>
        <ul className="space-y-1">
          {products.map((product) => (
            <li key={product.id} className="flex items-center justify-between gap-3 text-sm">
              <span>
                {product.name} · {product.price.formatted}
              </span>
              <button type="button" onClick={() => removeProduct(product.id)} className="text-xs text-red-500">
                {t("common.remove")}
              </button>
            </li>
          ))}
          {products.length === 0 ? <p className="text-sm text-muted">{t("bot.commerce.noProducts")}</p> : null}
        </ul>
        <form onSubmit={addProduct} className="flex flex-wrap gap-2">
          <input
            className="field flex-1"
            placeholder={t("bot.commerce.productNamePlaceholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            type="number"
            min={0}
            step="0.01"
            className="field w-28"
            placeholder={t("bot.commerce.pricePlaceholder")}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            required
          />
          <button type="submit" disabled={busy} className="btn-primary shrink-0">
            {t("common.add")}
          </button>
        </form>
      </div>

      {activeOrders.length > 0 ? (
        <div className="space-y-2 border-t border-line pt-4">
          <h3 className="text-sm font-medium text-muted">{t("bot.commerce.orders")}</h3>
          <ul className="space-y-1">
            {activeOrders.map((order) => (
              <li key={order.id} className="flex items-center justify-between gap-3 text-sm">
                <span>
                  {order.subtotal.formatted} · {order.items.length} {t("bot.commerce.items")}
                  {order.contact_name ? ` · ${order.contact_name}` : ""}
                </span>
                <button type="button" onClick={() => cancelOrder(order.id)} className="text-xs text-red-500">
                  {t("common.cancel")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {activeReservations.length > 0 ? (
        <div className="space-y-2 border-t border-line pt-4">
          <h3 className="text-sm font-medium text-muted">{t("bot.commerce.reservations")}</h3>
          <ul className="space-y-1">
            {activeReservations.map((reservation) => (
              <li key={reservation.id} className="flex items-center justify-between gap-3 text-sm">
                <span>
                  {new Date(reservation.starts_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")} ·{" "}
                  {reservation.party_size} {t("bot.commerce.people")}
                </span>
                <button
                  type="button"
                  onClick={() => cancelReservation(reservation.id)}
                  className="text-xs text-red-500"
                >
                  {t("common.cancel")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
