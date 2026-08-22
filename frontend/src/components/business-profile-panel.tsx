"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError, mediaUrl } from "@/lib/api";
import { botsApi, type BusinessProfileView, type WorkingHoursRow } from "@/lib/bots";

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

const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

function emptyWeek(): WorkingHoursRow[] {
  return WEEKDAYS.map((weekday) => ({ weekday, opens_at: null, closes_at: null, is_closed: true }));
}

function WorkingHoursEditor({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();
  const [days, setDays] = useState<WorkingHoursRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    botsApi.workingHours(botId, locale).then((body) => {
      const byWeekday = new Map(body.days.map((row) => [row.weekday, row]));
      setDays(WEEKDAYS.map((weekday) => byWeekday.get(weekday) ?? {
        weekday,
        opens_at: null,
        closes_at: null,
        is_closed: true,
      }));
    });
  }, [botId, locale]);

  function updateDay(weekday: number, patch: Partial<WorkingHoursRow>) {
    setDays((current) =>
      (current ?? emptyWeek()).map((row) => (row.weekday === weekday ? { ...row, ...patch } : row)),
    );
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!days) return;
    setBusy(true);
    setSaved(false);
    try {
      const body = await botsApi.updateWorkingHours(botId, days, locale);
      setDays(body.days);
      setSaved(true);
    } finally {
      setBusy(false);
    }
  }

  if (!days) return <p className="text-sm text-muted">{t("common.loading")}</p>;

  return (
    <form onSubmit={save} className="space-y-2 border-t border-line pt-3">
      <h3 className="text-sm font-medium text-muted">{t("bot.businessProfile.structuredHoursTitle")}</h3>
      <p className="text-xs text-muted">{t("bot.businessProfile.structuredHoursHint")}</p>
      <div className="space-y-1.5">
        {days.map((row) => (
          <div key={row.weekday} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="w-24 shrink-0">{t(`bot.businessProfile.weekday.${row.weekday}`)}</span>
            <label className="flex items-center gap-1 text-xs text-muted">
              <input
                type="checkbox"
                checked={row.is_closed}
                onChange={(e) => updateDay(row.weekday, { is_closed: e.target.checked })}
              />
              {t("bot.businessProfile.closed")}
            </label>
            {!row.is_closed ? (
              <>
                <input
                  type="time"
                  className="field w-auto py-1"
                  value={row.opens_at ?? ""}
                  onChange={(e) => updateDay(row.weekday, { opens_at: e.target.value })}
                  required
                />
                <input
                  type="time"
                  className="field w-auto py-1"
                  value={row.closes_at ?? ""}
                  onChange={(e) => updateDay(row.weekday, { closes_at: e.target.value })}
                  required
                />
              </>
            ) : null}
          </div>
        ))}
      </div>
      {saved && !busy ? <p className="text-sm text-green-600">{t("common.saved")}</p> : null}
      <button type="submit" disabled={busy} className="btn-primary">
        {busy ? t("common.loading") : t("bot.businessProfile.saveHours")}
      </button>
    </form>
  );
}

export function BusinessProfilePanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [profile, setProfile] = useState<BusinessProfileView | null>(null);
  const [form, setForm] = useState<BusinessProfileView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  function load() {
    botsApi
      .businessProfile(botId, locale)
      .then((data) => {
        setProfile(data);
        setForm(data);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }

  useEffect(load, [botId, locale, t]);

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

  async function uploadLogo(file: File | undefined) {
    if (!file) return;
    try {
      await botsApi.uploadBusinessLogo(botId, file, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
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

      <div className="flex items-center gap-3">
        {form.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(form.logo_url)}
            alt=""
            className="h-14 w-14 rounded-lg border border-line object-cover"
          />
        ) : null}
        <label className="btn-ghost cursor-pointer px-3 py-1.5 text-sm">
          {t("bot.businessProfile.uploadLogo")}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(event) => {
              void uploadLogo(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </label>
      </div>

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

      <WorkingHoursEditor botId={botId} />
    </section>
  );
}
