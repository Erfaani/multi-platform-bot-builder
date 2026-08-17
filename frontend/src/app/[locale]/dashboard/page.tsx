"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatMoney, type CurrencyMeta } from "@/lib/format";

export default function DashboardPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const { user, tenants, activeTenantId, selectTenant, loading, reload } = useAuth();

  const [currencies, setCurrencies] = useState<CurrencyMeta[]>([]);
  const [newWorkspace, setNewWorkspace] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    api
      .currencies(locale)
      .then((rows) => setCurrencies(rows as CurrencyMeta[]))
      .catch(() => setCurrencies([]));
  }, [locale]);

  async function createWorkspace(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tenant = await api.createTenant(newWorkspace, locale);
      setNewWorkspace("");
      await reload();
      selectTenant(tenant.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;

  const active = tenants.find((tenant) => tenant.id === activeTenantId);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">{t("dashboard.title")}</h1>
        <p className="text-muted">{t("dashboard.welcome", { name: user.full_name })}</p>
      </div>

      <section className="card space-y-3">
        <h2 className="font-medium">{t("dashboard.workspace")}</h2>

        {tenants.length === 0 ? (
          <p className="text-sm text-muted">{t("dashboard.noWorkspace")}</p>
        ) : (
          <div className="space-y-2">
            <label className="block space-y-1">
              <span className="text-sm text-muted">{t("dashboard.selectWorkspace")}</span>
              <select
                className="field"
                value={activeTenantId ?? ""}
                onChange={(event) => selectTenant(event.target.value)}
              >
                {tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </option>
                ))}
              </select>
            </label>
            {active ? (
              <p className="text-sm text-muted">
                {t("dashboard.role")}: {active.my_role} · {active.default_currency}
              </p>
            ) : null}
          </div>
        )}

        <form onSubmit={createWorkspace} className="flex gap-2 pt-2">
          <input
            className="field"
            placeholder={t("dashboard.workspaceName")}
            value={newWorkspace}
            onChange={(event) => setNewWorkspace(event.target.value)}
            required
          />
          <button type="submit" disabled={busy} className="btn-primary shrink-0">
            {t("dashboard.createWorkspace")}
          </button>
        </form>

        {error ? (
          <p role="alert" className="text-sm text-red-500">
            {error}
          </p>
        ) : null}
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <Link href={`/${locale}/bots`} className="card transition hover:border-accent">
          <h2 className="font-medium">{t("dashboard.myBots")}</h2>
          <p className="text-sm text-muted">{t("bots.title")}</p>
        </Link>
        <Link href={`/${locale}/orders`} className="card transition hover:border-accent">
          <h2 className="font-medium">{t("dashboard.orders")}</h2>
          <p className="text-sm text-muted">{t("orders.title")}</p>
        </Link>
      </section>

      <section className="card space-y-2">
        <h2 className="font-medium">{t("dashboard.currencies")}</h2>
        <ul className="space-y-1 text-sm text-muted">
          {currencies.map((currency) => (
            <li key={currency.code}>
              {currency.code} —{" "}
              {formatMoney({ amount_minor: 149 * 10 ** currency.exponent, currency: currency.code },
                locale,
                currency,
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
