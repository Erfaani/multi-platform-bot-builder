"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AddonFeaturesPanel } from "@/components/addon-features-panel";
import { AiPanel } from "@/components/ai-panel";
import { AnalyticsPanel } from "@/components/analytics-panel";
import { AppointmentsPanel } from "@/components/appointments-panel";
import { BroadcastPanel } from "@/components/broadcast-panel";
import { BusinessProfilePanel } from "@/components/business-profile-panel";
import { CommercePanel } from "@/components/commerce-panel";
import { CoursePanel } from "@/components/course-panel";
import { CrmPanel } from "@/components/crm-panel";
import { FaqPanel } from "@/components/faq-panel";
import { InputRestrictionsPanel } from "@/components/input-restrictions-panel";
import { PlatformIcon } from "@/components/platform-icon";
import { PropertyPanel } from "@/components/property-panel";
import { SubscriptionPanel } from "@/components/subscription-panel";
import { TokenHandoff } from "@/components/token-handoff";
import { LOCALES } from "@/i18n/config";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { botsApi, type BotView } from "@/lib/bots";

/** Saga steps, in order, mapped to what a customer should be told (spec §20). */
const STEP_ORDER = [
  "create_bot_record",
  "enable_features",
  "acquire_credential",
  "verify_get_me",
  "apply_configuration",
  "set_commands",
  "set_webhook",
  "smoke_test",
  "activate",
] as const;

function ProvisioningProgress({ bot }: { bot: BotView }) {
  const t = useTranslations();
  if (!bot.provisioning || bot.status === "ACTIVE") return null;

  const byStep = new Map(bot.provisioning.steps.map((s) => [s.slug, s.status]));

  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{t("bot.provisioning.title")}</h2>

      {bot.provisioning.status === "AWAITING_CUSTOMER" ? (
        <p className="text-sm text-muted">{t("bot.provisioning.awaitingCustomer")}</p>
      ) : null}

      {bot.provisioning.error_code ? (
        <p className="rounded-lg border border-red-500/40 p-3 text-sm text-red-500">
          {t("bot.provisioning.failed", { code: bot.provisioning.error_code })}
        </p>
      ) : null}

      <ol className="space-y-1 text-sm">
        {STEP_ORDER.map((slug) => {
          const status = byStep.get(slug) ?? "PENDING";
          const mark =
            status === "SUCCEEDED"
              ? "✓"
              : status === "FAILED"
                ? "✕"
                : status === "BLOCKED"
                  ? "⏸"
                  : "·";
          const tone =
            status === "SUCCEEDED"
              ? "text-green-600"
              : status === "FAILED"
                ? "text-red-500"
                : status === "BLOCKED"
                  ? "text-amber-600"
                  : "text-muted";
          return (
            <li key={slug} className={`flex gap-3 ${tone}`}>
              <span className="w-4">{mark}</span>
              <span>{t(`bot.step.${slug}`)}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default function BotDetailPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const { user, loading } = useAuth();

  const [bot, setBot] = useState<BotView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [welcome, setWelcome] = useState("");
  const [name, setName] = useState("");
  const [defaultLocale, setDefaultLocale] = useState("");
  const [timezone, setTimezone] = useState("");
  const [saving, setSaving] = useState(false);
  const [rotatingInstanceId, setRotatingInstanceId] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!params?.id) return;
    botsApi
      .get(params.id, locale)
      .then(setBot)
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }, [params?.id, locale, t]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  // Pre-fill the settings form once per bot — keyed on id, not the whole object, so a
  // background poll (see below) never clobbers text the customer is mid-typing.
  useEffect(() => {
    if (!bot) return;
    setName(bot.name);
    setDefaultLocale(bot.default_locale);
    setTimezone(bot.timezone);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot?.id]);

  // Poll while provisioning is in flight, so the customer sees real progress.
  useEffect(() => {
    if (!bot || bot.status === "ACTIVE" || bot.status === "FAILED") return;
    if (bot.provisioning?.status === "AWAITING_CUSTOMER") return;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [bot, load]);

  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    if (!bot) return;
    setSaving(true);
    try {
      setBot(
        await botsApi.updateConfiguration(
          bot.id,
          { name, welcome_message: welcome, default_locale: defaultLocale, timezone },
          locale,
        ),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setSaving(false);
    }
  }

  async function rotateWebhook(instanceId: string) {
    if (!bot) return;
    if (!window.confirm(t("bot.channels.rotateWebhookConfirm"))) return;
    setRotatingInstanceId(instanceId);
    try {
      setBot(await botsApi.rotateWebhook(bot.id, instanceId, locale));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setRotatingInstanceId(null);
    }
  }

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;
  if (error && !bot) return <p className="text-sm text-red-500">{error}</p>;
  if (!bot) return <p className="text-muted">{t("common.loading")}</p>;

  const pending = bot.instances.filter((i) => i.needs_token);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href={`/${locale}/bots`} className="text-xs text-muted hover:text-ink">
            ← {t("bots.title")}
          </Link>
          <h1 className="text-2xl font-semibold">{bot.name}</h1>
        </div>
        <span className="rounded-md border border-line px-2 py-0.5 text-xs">
          {t(`bot.status.${bot.status}`)}
        </span>
      </div>

      {pending.map((instance) => (
        <TokenHandoff key={instance.id} botId={bot.id} instance={instance} onDone={load} />
      ))}

      <ProvisioningProgress bot={bot} />

      <section className="card space-y-2">
        <h2 className="font-medium">{t("bot.channels")}</h2>
        {bot.instances.map((instance) => (
          <div key={instance.id} className="flex items-center justify-between gap-3 text-sm">
            <span className="flex items-center gap-2">
              <PlatformIcon slug={instance.platform} size={18} />
              <span>
                <span className="block capitalize">{instance.platform}</span>
                <span className="block text-xs text-muted">
                  {t(`bot.instanceStatus.${instance.status}`)}
                  {instance.acquisition_mode === "POOL"
                    ? ` · ${t("bot.tier.instant")}`
                    : instance.acquisition_mode === "TOKEN_HANDOFF"
                      ? ` · ${t("bot.tier.custom")}`
                      : ""}
                </span>
              </span>
            </span>
            <span className="flex items-center gap-3">
              {instance.link ? (
                <a
                  href={instance.link}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent"
                  dir="ltr"
                >
                  @{instance.username}
                </a>
              ) : (
                <span className="text-xs text-muted">—</span>
              )}
              {instance.status === "ACTIVE" ? (
                <button
                  type="button"
                  onClick={() => rotateWebhook(instance.id)}
                  disabled={rotatingInstanceId === instance.id}
                  className="text-xs text-muted hover:text-ink"
                >
                  {t("bot.channels.rotateWebhook")}
                </button>
              ) : null}
            </span>
          </div>
        ))}
      </section>

      <section className="card space-y-2">
        <h2 className="font-medium">{t("bot.features")}</h2>
        <p className="text-sm text-muted">{bot.features.join(" · ") || "—"}</p>
      </section>

      {bot.subscription ? <SubscriptionPanel subscription={bot.subscription} /> : null}

      {bot.status === "ACTIVE" ? (
        <>
          <BusinessProfilePanel botId={bot.id} />
          <FaqPanel botId={bot.id} />
          {bot.features.includes("appointment") ? <AppointmentsPanel botId={bot.id} /> : null}
          {bot.features.includes("product_catalog") || bot.features.includes("table_reservation") ? (
            <CommercePanel botId={bot.id} />
          ) : null}
          {bot.features.includes("property_listings") ? <PropertyPanel botId={bot.id} /> : null}
          {bot.features.includes("course_catalog") ? <CoursePanel botId={bot.id} /> : null}
          {bot.features.includes("lead_capture") ||
          bot.features.includes("contact_request") ||
          bot.features.includes("consultation_request") ||
          bot.features.includes("feedback") ? (
            <CrmPanel botId={bot.id} />
          ) : null}
          {bot.features.includes("consultation_request") ? (
            <InputRestrictionsPanel botId={bot.id} />
          ) : null}
          {bot.features.includes("customer_broadcast") ? <BroadcastPanel botId={bot.id} /> : null}
          {bot.features.includes("ai_assistant") ? (
            <AiPanel botId={bot.id} hasKnowledgeBase={bot.features.includes("ai_knowledge_base")} />
          ) : null}
          <AddonFeaturesPanel botId={bot.id} />
          <AnalyticsPanel botId={bot.id} />
        </>
      ) : null}

      <section className="card space-y-3">
        <h2 className="font-medium">{t("bot.settings")}</h2>
        <form onSubmit={saveSettings} className="space-y-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="text-sm text-muted">{t("bot.settings.name")}</span>
              <input className="field" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label className="block space-y-1">
              <span className="text-sm text-muted">{t("bot.settings.locale")}</span>
              <select
                className="field"
                value={defaultLocale}
                onChange={(event) => setDefaultLocale(event.target.value)}
              >
                {LOCALES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.settings.timezone")}</span>
            <input className="field" dir="ltr" value={timezone} onChange={(event) => setTimezone(event.target.value)} />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("builder.customize.welcome")}</span>
            <textarea
              className="field"
              rows={3}
              value={welcome}
              onChange={(event) => setWelcome(event.target.value)}
              placeholder={t("builder.customize.welcomePlaceholder")}
            />
          </label>
          <button type="submit" disabled={saving} className="btn-primary">
            {saving ? t("common.loading") : t("common.save")}
          </button>
        </form>
      </section>

      {error ? (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      ) : null}
    </div>
  );
}
