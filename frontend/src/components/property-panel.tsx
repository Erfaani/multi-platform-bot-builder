"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError, mediaUrl } from "@/lib/api";
import {
  commerceApi,
  type PropertyListingType,
  type PropertyListingView,
  type PropertyType,
} from "@/lib/commerce";

const LISTING_TYPES: PropertyListingType[] = ["SALE", "RENT"];
const PROPERTY_TYPES: PropertyType[] = ["APARTMENT", "HOUSE", "LAND", "COMMERCIAL", "OTHER"];

function PropertyEditForm({
  listing,
  botId,
  onDone,
}: {
  listing: PropertyListingView;
  botId: string;
  onDone: () => void;
}) {
  const t = useTranslations();
  const { locale } = useIntl();
  const [title, setTitle] = useState(listing.title);
  const [listingType, setListingType] = useState(listing.listing_type);
  const [propertyType, setPropertyType] = useState(listing.property_type);
  const [price, setPrice] = useState(String(listing.price.amount_minor / 100));
  const [address, setAddress] = useState(listing.address);
  const [description, setDescription] = useState(listing.description);
  const [busy, setBusy] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const priceMinor = Math.round(Number(price) * 100);
    if (!title.trim() || !Number.isFinite(priceMinor) || priceMinor < 0) return;

    setBusy(true);
    try {
      await commerceApi.updateProperty(
        botId,
        listing.id,
        { title, listing_type: listingType, property_type: propertyType, price_minor: priceMinor, address, description },
        locale,
      );
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="grid gap-2 border-t border-line pt-2 sm:grid-cols-2">
      <input className="field sm:col-span-2" value={title} onChange={(e) => setTitle(e.target.value)} required />
      <select
        className="field"
        value={listingType}
        onChange={(e) => setListingType(e.target.value as PropertyListingType)}
      >
        {LISTING_TYPES.map((value) => (
          <option key={value} value={value}>
            {t(`bot.properties.listingType.${value}`)}
          </option>
        ))}
      </select>
      <select
        className="field"
        value={propertyType}
        onChange={(e) => setPropertyType(e.target.value as PropertyType)}
      >
        {PROPERTY_TYPES.map((value) => (
          <option key={value} value={value}>
            {t(`bot.properties.propertyType.${value}`)}
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
        className="field"
        placeholder={t("bot.properties.addressPlaceholder")}
        value={address}
        onChange={(e) => setAddress(e.target.value)}
      />
      <textarea
        className="field sm:col-span-2"
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
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

export function PropertyPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [listings, setListings] = useState<PropertyListingView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  const [title, setTitle] = useState("");
  const [listingType, setListingType] = useState<PropertyListingType>("SALE");
  const [propertyType, setPropertyType] = useState<PropertyType>("APARTMENT");
  const [price, setPrice] = useState("");

  function load() {
    commerceApi.properties(botId, locale).then(setListings).catch(() => setError(t("error.network")));
  }

  useEffect(load, [botId, locale, t]);

  async function addListing(event: React.FormEvent) {
    event.preventDefault();
    const priceMinor = Math.round(Number(price) * 100);
    if (!title.trim() || !Number.isFinite(priceMinor) || priceMinor < 0) return;

    setBusy(true);
    setError(null);
    try {
      await commerceApi.createProperty(
        botId,
        { title, listing_type: listingType, property_type: propertyType, price_minor: priceMinor },
        locale,
      );
      setTitle("");
      setPrice("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(propertyId: number) {
    try {
      await commerceApi.deleteProperty(botId, propertyId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function addPhoto(propertyId: number, file: File | undefined) {
    if (!file) return;
    try {
      await commerceApi.addPropertyImage(botId, propertyId, file, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function removePhoto(imageId: number) {
    try {
      await commerceApi.deletePropertyImage(botId, imageId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  return (
    <section className="card space-y-5">
      <h2 className="font-medium">{t("bot.properties.title")}</h2>
      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <ul className="space-y-2">
        {listings.map((listing) => (
          <li key={listing.id} className="space-y-1.5 rounded-lg border border-line p-2 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span>
                {listing.title} · {listing.price.formatted} ·{" "}
                {t(`bot.properties.listingType.${listing.listing_type}`)}
              </span>
              <span className="flex shrink-0 gap-2 text-xs">
                <button type="button" onClick={() => setEditingId(editingId === listing.id ? null : listing.id)}>
                  {t("common.edit")}
                </button>
                <button type="button" onClick={() => remove(listing.id)} className="text-red-500">
                  {t("common.remove")}
                </button>
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {listing.images.map((image) => (
                <span key={image.id} className="group relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={mediaUrl(image.url)}
                    alt=""
                    className="h-12 w-12 rounded-md border border-line object-cover"
                  />
                  <button
                    type="button"
                    onClick={() => removePhoto(image.id)}
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
                    void addPhoto(listing.id, event.target.files?.[0]);
                    event.target.value = "";
                  }}
                />
              </label>
            </div>
            {editingId === listing.id ? (
              <PropertyEditForm
                listing={listing}
                botId={botId}
                onDone={() => {
                  setEditingId(null);
                  load();
                }}
              />
            ) : null}
          </li>
        ))}
        {listings.length === 0 ? <p className="text-sm text-muted">{t("bot.properties.empty")}</p> : null}
      </ul>

      <form onSubmit={addListing} className="grid gap-2 border-t border-line pt-4 sm:grid-cols-2">
        <input
          className="field sm:col-span-2"
          placeholder={t("bot.properties.titlePlaceholder")}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
        <select
          className="field"
          value={listingType}
          onChange={(e) => setListingType(e.target.value as PropertyListingType)}
        >
          {LISTING_TYPES.map((value) => (
            <option key={value} value={value}>
              {t(`bot.properties.listingType.${value}`)}
            </option>
          ))}
        </select>
        <select
          className="field"
          value={propertyType}
          onChange={(e) => setPropertyType(e.target.value as PropertyType)}
        >
          {PROPERTY_TYPES.map((value) => (
            <option key={value} value={value}>
              {t(`bot.properties.propertyType.${value}`)}
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
        <button type="submit" disabled={busy} className="btn-primary sm:col-span-2">
          {t("bot.properties.add")}
        </button>
      </form>
    </section>
  );
}
