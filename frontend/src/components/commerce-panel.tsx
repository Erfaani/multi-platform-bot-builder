"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError, mediaUrl } from "@/lib/api";
import {
  commerceApi,
  type BusinessOrderView,
  type ProductCategoryView,
  type ProductView,
  type TableReservationView,
} from "@/lib/commerce";

function ProductEditForm({
  product,
  categories,
  botId,
  onDone,
}: {
  product: ProductView;
  categories: ProductCategoryView[];
  botId: string;
  onDone: () => void;
}) {
  const t = useTranslations();
  const { locale } = useIntl();
  const [name, setName] = useState(product.name);
  const [description, setDescription] = useState(product.description);
  const [price, setPrice] = useState(String(product.price.amount_minor / 100));
  const [stock, setStock] = useState(product.stock === null ? "" : String(product.stock));
  const [categoryId, setCategoryId] = useState(product.category_id === null ? "" : String(product.category_id));
  const [busy, setBusy] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const priceMinor = Math.round(Number(price) * 100);
    if (!name.trim() || !Number.isFinite(priceMinor) || priceMinor < 0) return;

    setBusy(true);
    try {
      await commerceApi.updateProduct(
        botId,
        product.id,
        {
          name,
          description,
          price_minor: priceMinor,
          stock: stock === "" ? null : Number(stock),
          category_id: categoryId === "" ? null : Number(categoryId),
        },
        locale,
      );
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="grid gap-2 border-t border-line pt-2 sm:grid-cols-2">
      <input className="field sm:col-span-2" value={name} onChange={(e) => setName(e.target.value)} required />
      <textarea
        className="field sm:col-span-2"
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <select className="field" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
        <option value="">{t("bot.commerce.uncategorized")}</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </select>
      <input
        type="number"
        min={0}
        step="0.01"
        className="field"
        placeholder={t("bot.commerce.pricePlaceholder")}
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        required
      />
      <input
        type="number"
        min={0}
        className="field sm:col-span-2"
        placeholder={t("bot.commerce.stockPlaceholder")}
        value={stock}
        onChange={(e) => setStock(e.target.value)}
      />
      <div className="flex gap-2 sm:col-span-2">
        <button type="submit" disabled={busy} className="btn-primary">
          {t("common.save")}
        </button>
        <button type="button" onClick={onDone} className="btn-ghost">
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

export function CommercePanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [products, setProducts] = useState<ProductView[]>([]);
  const [categories, setCategories] = useState<ProductCategoryView[]>([]);
  const [orders, setOrders] = useState<BusinessOrderView[]>([]);
  const [reservations, setReservations] = useState<TableReservationView[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    commerceApi.products(botId, locale).then(setProducts).catch(() => setError(t("error.network")));
    commerceApi.categories(botId, locale).then(setCategories).catch(() => {});
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
      await commerceApi.createProduct(
        botId,
        { name, price_minor: priceMinor, category_id: categoryId === "" ? null : Number(categoryId) },
        locale,
      );
      setName("");
      setPrice("");
      setCategoryId("");
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

  async function addProductPhoto(productId: number, file: File | undefined) {
    if (!file) return;
    try {
      await commerceApi.addProductImage(botId, productId, file, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function removeProductPhoto(imageId: number) {
    try {
      await commerceApi.deleteProductImage(botId, imageId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function addCategory(event: React.FormEvent) {
    event.preventDefault();
    if (!categoryName.trim()) return;
    setBusy(true);
    try {
      await commerceApi.createCategory(botId, categoryName.trim(), locale);
      setCategoryName("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function removeCategory(categoryId: number) {
    try {
      await commerceApi.deleteCategory(botId, categoryId, locale);
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
  const categoryLabel = (id: number | null) => categories.find((c) => c.id === id)?.name;

  return (
    <section className="card space-y-5">
      <h2 className="font-medium">{t("bot.commerce.title")}</h2>
      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-muted">{t("bot.commerce.categories")}</h3>
        <ul className="flex flex-wrap gap-2">
          {categories.map((category) => (
            <li
              key={category.id}
              className="flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs"
            >
              {category.name}
              <button type="button" onClick={() => removeCategory(category.id)} className="text-red-500">
                ×
              </button>
            </li>
          ))}
          {categories.length === 0 ? <p className="text-sm text-muted">{t("bot.commerce.noCategories")}</p> : null}
        </ul>
        <form onSubmit={addCategory} className="flex gap-2">
          <input
            className="field flex-1"
            placeholder={t("bot.commerce.categoryNamePlaceholder")}
            value={categoryName}
            onChange={(e) => setCategoryName(e.target.value)}
          />
          <button type="submit" disabled={busy} className="btn-ghost shrink-0">
            {t("bot.commerce.addCategory")}
          </button>
        </form>
      </div>

      <div className="space-y-2 border-t border-line pt-4">
        <h3 className="text-sm font-medium text-muted">{t("bot.commerce.products")}</h3>
        <ul className="space-y-2">
          {products.map((product) => (
            <li key={product.id} className="space-y-1.5 rounded-lg border border-line p-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span>
                  {product.name} · {product.price.formatted}
                  {categoryLabel(product.category_id) ? ` · ${categoryLabel(product.category_id)}` : ""}
                </span>
                <span className="flex shrink-0 gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => setEditingId(editingId === product.id ? null : product.id)}
                  >
                    {t("common.edit")}
                  </button>
                  <button type="button" onClick={() => removeProduct(product.id)} className="text-red-500">
                    {t("common.remove")}
                  </button>
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {product.images.map((image) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <span key={image.id} className="group relative">
                    <img
                      src={mediaUrl(image.url)}
                      alt=""
                      className="h-12 w-12 rounded-md border border-line object-cover"
                    />
                    <button
                      type="button"
                      onClick={() => removeProductPhoto(image.id)}
                      className="absolute -end-1 -top-1 hidden h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] text-white group-hover:flex"
                      aria-label={t("common.remove")}
                    >
                      ×
                    </button>
                  </span>
                ))}
                <label className="btn-ghost cursor-pointer px-2 py-1 text-xs">
                  {t("bot.commerce.addPhoto")}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(event) => {
                      void addProductPhoto(product.id, event.target.files?.[0]);
                      event.target.value = "";
                    }}
                  />
                </label>
              </div>
              {editingId === product.id ? (
                <ProductEditForm
                  product={product}
                  categories={categories}
                  botId={botId}
                  onDone={() => {
                    setEditingId(null);
                    load();
                  }}
                />
              ) : null}
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
          <select className="field w-auto" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">{t("bot.commerce.uncategorized")}</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
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
