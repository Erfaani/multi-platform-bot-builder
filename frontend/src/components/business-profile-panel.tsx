"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { botsApi, type BusinessProfileView } from "@/lib/bots";

const FIELDS: (keyof BusinessProfileView)[] = [
  "display_name",
  "description",
  "phone",
  "secondary_phone",
  "email",
  "website",
  "address",
  "city",
  "working_hours_text",
];

export function BusinessProfilePanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [profile, setProfile] = useState<BusinessProfileView | null>(null);
  const [form, setForm] = useState<BusinessProfileView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    botsApi
      .businessProfile(botId, locale)
      .then((data) => {
        setProfile(data);
        setForm(data);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }, [botId, locale, t]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!form || !profile) return;

    const changed: Partial<BusinessProfileView> = {};
    for (const field of FIELDS) {
      if (form[field] !== profile[field]) changed[field] = form[field];
    }
    if (Object.keys(changed).length === 0) return;

    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await botsApi.updateBusinessProfile(botId, changed, locale);
      setProfile(updated);
      setForm(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  if (!form) {
    return error ? (
      <p className="text-sm text-red-500">{error}</p>
    ) : (
      <p className="text-sm text-muted">{t("common.loading")}</p>
    );
  }

  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{t("bot.businessProfile.title")}</h2>
      <p className="text-sm text-muted">{t("bot.businessProfile.hint")}</p>

      <form onSubmit={save} className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("bot.businessProfile.displayName")}</span>
          <input
            className="field"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("bot.businessProfile.description")}</span>
          <textarea
            className="field"
            rows={2}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.businessProfile.phone")}</span>
            <input
              className="field"
              dir="ltr"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.businessProfile.secondaryPhone")}</span>
            <input
              className="field"
              dir="ltr"
              value={form.secondary_phone}
              onChange={(e) => setForm({ ...form, secondary_phone: e.target.value })}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.businessProfile.email")}</span>
            <input
              type="email"
              className="field"
              dir="ltr"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.businessProfile.website")}</span>
            <input
              className="field"
              dir="ltr"
              value={form.website}
              onChange={(e) => setForm({ ...form, website: e.target.value })}
            />
          </label>
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("bot.businessProfile.address")}</span>
          <input
            className="field"
            value={form.address}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
          />
        </label>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.businessProfile.city")}</span>
            <input
              className="field"
              value={form.city}
              onChange={(e) => setForm({ ...form, city: e.target.value })}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.businessProfile.workingHours")}</span>
            <input
              className="field"
              value={form.working_hours_text}
              onChange={(e) => setForm({ ...form, working_hours_text: e.target.value })}
            />
          </label>
        </div>

        {error ? (
          <p role="alert" className="text-sm text-red-500">
            {error}
          </p>
        ) : null}
        {saved && !busy ? <p className="text-sm text-green-600">{t("common.saved")}</p> : null}

        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? t("common.loading") : t("common.save")}
        </button>
      </form>
    </section>
  );
}
