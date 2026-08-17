"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BotPreview } from "@/components/bot-preview";
import { PriceSummary } from "@/components/price-summary";
import type { Locale } from "@/i18n/config";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { checkoutApi } from "@/lib/checkout";
import {
  builderApi,
  quoteSession,
  type BusinessTemplate,
  type FeatureItem,
  type PlatformOption,
  type PlatformPreview,
  type QuoteView,
} from "@/lib/builder";
import { useAuth } from "@/lib/auth";

/** Spec §8. Steps 8–9 (order, payment) arrive in Phase 3. */
const STEPS = [
  "platform",
  "business_type",
  "business_info",
  "features",
  "customize",
  "preview",
  "price",
] as const;

type Step = (typeof STEPS)[number];

interface BusinessDraft {
  name: string;
  description: string;
  phone: string;
  address: string;
  welcome_message: string;
  bot_locale: string;
}

const EMPTY_DRAFT: BusinessDraft = {
  name: "",
  description: "",
  phone: "",
  address: "",
  welcome_message: "",
  bot_locale: "",
};

export default function BuildPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const { user } = useAuth();

  const [stepIndex, setStepIndex] = useState(0);
  const step: Step = STEPS[stepIndex];

  const [platforms, setPlatforms] = useState<PlatformOption[]>([]);
  const [templates, setTemplates] = useState<BusinessTemplate[]>([]);
  const [features, setFeatures] = useState<FeatureItem[]>([]);

  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [templateSlug, setTemplateSlug] = useState<string>("");
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);
  const [draft, setDraft] = useState<BusinessDraft>(EMPTY_DRAFT);
  const [currency, setCurrency] = useState<string>("USD");

  const [quote, setQuote] = useState<QuoteView | null>(null);
  const [previews, setPreviews] = useState<PlatformPreview[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pricing, setPricing] = useState(false);

  const quoteRef = useRef<{ id: string; secret: string } | null>(null);

  // --- catalogue -----------------------------------------------------------
  useEffect(() => {
    Promise.all([
      builderApi.platforms(locale),
      builderApi.templates(locale),
      builderApi.features(locale),
    ])
      .then(([p, tpl, f]) => {
        setPlatforms(p);
        setTemplates(tpl);
        setFeatures(f);
      })
      .catch(() => setError(t("error.network")));
  }, [locale, t]);

  const template = useMemo(
    () => templates.find((item) => item.slug === templateSlug) ?? null,
    [templates, templateSlug],
  );

  // Features this template offers, in its own order.
  const offered = useMemo(() => {
    if (!template) return [];
    const bySlug = new Map(features.map((f) => [f.slug, f]));
    return template.features
      .map((ref) => ({ ref, feature: bySlug.get(ref.slug) }))
      .filter((row): row is { ref: typeof row.ref; feature: FeatureItem } => !!row.feature);
  }, [template, features]);

  function chooseTemplate(slug: string) {
    setTemplateSlug(slug);
    const chosen = templates.find((item) => item.slug === slug);
    // Start from the template's own recommendation rather than an empty basket.
    setSelectedFeatures(chosen ? [...chosen.default_features] : []);
  }

  function togglePlatform(slug: string) {
    setSelectedPlatforms((current) =>
      current.includes(slug) ? current.filter((item) => item !== slug) : [...current, slug],
    );
  }

  function toggleFeature(slug: string, disabled: boolean) {
    if (disabled) return;
    setSelectedFeatures((current) =>
      current.includes(slug) ? current.filter((item) => item !== slug) : [...current, slug],
    );
  }

  /** A feature is unsellable if any chosen platform cannot run it. */
  const blockedFeatures = useMemo(() => {
    const blocked = new Map<string, string>();
    for (const feature of features) {
      for (const platform of selectedPlatforms) {
        const entry = feature.platforms?.[platform];
        if (entry && !entry.available) {
          blocked.set(feature.slug, entry.note || platform);
        }
      }
    }
    return blocked;
  }, [features, selectedPlatforms]);

  // Drop a selected feature the moment a platform choice makes it undeliverable,
  // so the customer never reaches the price step with an impossible basket.
  useEffect(() => {
    setSelectedFeatures((current) => current.filter((slug) => !blockedFeatures.has(slug)));
  }, [blockedFeatures]);

  // --- pricing -------------------------------------------------------------
  const reprice = useCallback(async () => {
    if (!templateSlug || selectedPlatforms.length === 0) return;

    setPricing(true);
    setError(null);
    try {
      const payload = {
        template: templateSlug,
        platforms: selectedPlatforms,
        features: selectedFeatures,
        currency,
        business: draft as unknown as Record<string, unknown>,
      };

      const existing = quoteRef.current;
      const result = existing
        ? await builderApi.updateQuote(existing.id, existing.secret, payload, locale)
        : await builderApi.createQuote(payload, locale);

      if (!existing && result.session_secret) {
        quoteRef.current = { id: result.id, secret: result.session_secret };
        quoteSession.write(result.id, result.session_secret);
      }
      setQuote(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setPricing(false);
    }
  }, [templateSlug, selectedPlatforms, selectedFeatures, currency, draft, locale, t]);

  // Live pricing, debounced so typing a business name does not hammer the API.
  useEffect(() => {
    if (!templateSlug || selectedPlatforms.length === 0) return;
    const timer = setTimeout(() => void reprice(), 400);
    return () => clearTimeout(timer);
  }, [reprice, templateSlug, selectedPlatforms]);

  // --- preview -------------------------------------------------------------
  useEffect(() => {
    if (step !== "preview" || !quoteRef.current) return;
    const { id, secret } = quoteRef.current;
    builderApi
      .preview(id, secret, locale)
      .then((result) => setPreviews(result.platforms))
      .catch(() => setError(t("error.generic")));
  }, [step, locale, quote?.resolved_features.join(","), t]);

  // --- navigation ----------------------------------------------------------
  const canAdvance = useMemo(() => {
    switch (step) {
      case "platform":
        return selectedPlatforms.length > 0;
      case "business_type":
        return Boolean(templateSlug);
      case "business_info":
        return draft.name.trim().length > 1;
      default:
        return true;
    }
  }, [step, selectedPlatforms, templateSlug, draft.name]);

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{t("builder.title")}</h1>
        <ol className="flex flex-wrap gap-2 text-xs">
          {STEPS.map((name, index) => (
            <li
              key={name}
              className={`rounded-md px-2 py-1 ${
                index === stepIndex
                  ? "bg-accent text-white"
                  : index < stepIndex
                    ? "border border-accent text-accent"
                    : "border border-line text-muted"
              }`}
            >
              {index + 1}. {t(`builder.step.${name}`)}
            </li>
          ))}
          <li className="rounded-md border border-dashed border-line px-2 py-1 text-muted">
            8. {t("builder.step.order")}
          </li>
        </ol>
      </header>

      {error ? (
        <p role="alert" className="rounded-lg border border-red-500/40 p-3 text-sm text-red-500">
          {error}
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section className="space-y-6">
          {step === "platform" ? (
            <StepPlatform
              platforms={platforms}
              selected={selectedPlatforms}
              onToggle={togglePlatform}
            />
          ) : null}

          {step === "business_type" ? (
            <StepTemplate templates={templates} selected={templateSlug} onSelect={chooseTemplate} />
          ) : null}

          {step === "business_info" ? (
            <StepBusinessInfo draft={draft} onChange={setDraft} />
          ) : null}

          {step === "features" ? (
            <StepFeatures
              offered={offered}
              selected={selectedFeatures}
              blocked={blockedFeatures}
              autoAdded={quote?.auto_added_features ?? []}
              onToggle={toggleFeature}
            />
          ) : null}

          {step === "customize" ? (
            <StepCustomize draft={draft} onChange={setDraft} currency={currency} onCurrency={setCurrency} />
          ) : null}

          {step === "preview" ? (
            <div className="space-y-3">
              <h2 className="font-medium">{t("builder.step.preview")}</h2>
              <p className="text-sm text-muted">{t("builder.preview.intro")}</p>
              <BotPreview previews={previews} />
            </div>
          ) : null}

          {step === "price" ? (
            <StepPrice
              quote={quote}
              isAuthenticated={Boolean(user)}
              locale={locale}
              quoteRef={quoteRef.current}
            />
          ) : null}

          <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
            <button
              type="button"
              className="btn-ghost"
              disabled={stepIndex === 0}
              onClick={() => setStepIndex((index) => Math.max(0, index - 1))}
            >
              {t("builder.back")}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!canAdvance || stepIndex === STEPS.length - 1}
              onClick={() => setStepIndex((index) => Math.min(STEPS.length - 1, index + 1))}
            >
              {t("builder.next")}
            </button>
          </div>
        </section>

        <PriceSummary quote={quote} busy={pricing} />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- steps

function StepPlatform({
  platforms,
  selected,
  onToggle,
}: {
  platforms: PlatformOption[];
  selected: string[];
  onToggle: (slug: string) => void;
}) {
  const t = useTranslations();
  return (
    <div className="space-y-3">
      <h2 className="font-medium">{t("builder.platform.title")}</h2>
      <p className="text-sm text-muted">{t("builder.platform.hint")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {platforms.map((platform) => {
          const active = selected.includes(platform.slug);
          return (
            <button
              key={platform.slug}
              type="button"
              onClick={() => onToggle(platform.slug)}
              aria-pressed={active}
              className={`card text-start transition ${active ? "border-accent" : ""}`}
            >
              <span className="block font-medium">{platform.name}</span>
              {!platform.capabilities_verified ? (
                <span className="block text-xs text-muted">
                  {t("builder.platform.provisional")}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepTemplate({
  templates,
  selected,
  onSelect,
}: {
  templates: BusinessTemplate[];
  selected: string;
  onSelect: (slug: string) => void;
}) {
  const t = useTranslations();
  return (
    <div className="space-y-3">
      <h2 className="font-medium">{t("builder.template.title")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {templates.map((template) => (
          <button
            key={template.slug}
            type="button"
            onClick={() => onSelect(template.slug)}
            aria-pressed={selected === template.slug}
            className={`card text-start transition ${
              selected === template.slug ? "border-accent" : ""
            }`}
          >
            <span className="block font-medium">{template.name}</span>
            <span className="block text-sm text-muted">{template.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function StepBusinessInfo({
  draft,
  onChange,
}: {
  draft: BusinessDraft;
  onChange: (draft: BusinessDraft) => void;
}) {
  const t = useTranslations();
  const field = (key: keyof BusinessDraft) => (
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => onChange({ ...draft, [key]: event.target.value });

  return (
    <div className="space-y-3">
      <h2 className="font-medium">{t("builder.business.title")}</h2>
      <p className="text-sm text-muted">{t("builder.business.hint")}</p>

      <label className="block space-y-1">
        <span className="text-sm text-muted">{t("builder.business.name")}</span>
        <input className="field" value={draft.name} onChange={field("name")} required />
      </label>

      <label className="block space-y-1">
        <span className="text-sm text-muted">{t("builder.business.description")}</span>
        <textarea
          className="field"
          rows={3}
          value={draft.description}
          onChange={field("description")}
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("builder.business.phone")}</span>
          <input className="field" value={draft.phone} onChange={field("phone")} />
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("builder.business.address")}</span>
          <input className="field" value={draft.address} onChange={field("address")} />
        </label>
      </div>
    </div>
  );
}

function StepFeatures({
  offered,
  selected,
  blocked,
  autoAdded,
  onToggle,
}: {
  offered: { ref: { slug: string; is_required: boolean }; feature: FeatureItem }[];
  selected: string[];
  blocked: Map<string, string>;
  autoAdded: string[];
  onToggle: (slug: string, disabled: boolean) => void;
}) {
  const t = useTranslations();

  return (
    <div className="space-y-3">
      <h2 className="font-medium">{t("builder.features.title")}</h2>

      {autoAdded.length > 0 ? (
        <p className="rounded-lg border border-line p-3 text-xs text-muted">
          {t("builder.features.autoAdded", { features: autoAdded.join(", ") })}
        </p>
      ) : null}

      <div className="grid gap-2">
        {offered.map(({ ref, feature }) => {
          const isBlocked = blocked.has(feature.slug);
          const locked = ref.is_required || feature.always_on;
          const active = locked || selected.includes(feature.slug);

          return (
            <button
              key={feature.slug}
              type="button"
              disabled={isBlocked || locked}
              onClick={() => onToggle(feature.slug, isBlocked || locked)}
              aria-pressed={active}
              className={`card flex items-start justify-between gap-3 text-start transition ${
                active ? "border-accent" : ""
              } ${isBlocked ? "opacity-50" : ""}`}
            >
              <span>
                <span className="block text-sm font-medium">{feature.name}</span>
                <span className="block text-xs text-muted">{feature.description}</span>
                {isBlocked ? (
                  <span className="mt-1 block text-xs text-red-500">
                    {t("builder.features.unavailable")} {blocked.get(feature.slug)}
                  </span>
                ) : null}
                {locked ? (
                  <span className="mt-1 block text-xs text-muted">
                    {t("builder.features.included")}
                  </span>
                ) : null}
              </span>
              <span className="text-xs text-muted">{active ? "✓" : ""}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepCustomize({
  draft,
  onChange,
  currency,
  onCurrency,
}: {
  draft: BusinessDraft;
  onChange: (draft: BusinessDraft) => void;
  currency: string;
  onCurrency: (currency: string) => void;
}) {
  const t = useTranslations();
  return (
    <div className="space-y-3">
      <h2 className="font-medium">{t("builder.customize.title")}</h2>

      <label className="block space-y-1">
        <span className="text-sm text-muted">{t("builder.customize.welcome")}</span>
        <textarea
          className="field"
          rows={3}
          value={draft.welcome_message}
          onChange={(event) => onChange({ ...draft, welcome_message: event.target.value })}
          placeholder={t("builder.customize.welcomePlaceholder")}
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("builder.customize.botLocale")}</span>
          <select
            className="field"
            value={draft.bot_locale}
            onChange={(event) => onChange({ ...draft, bot_locale: event.target.value })}
          >
            <option value="">{t("builder.customize.sameAsSite")}</option>
            <option value="en">English</option>
            <option value="fa">فارسی</option>
          </select>
        </label>

        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("builder.customize.currency")}</span>
          <select
            className="field"
            value={currency}
            onChange={(event) => onCurrency(event.target.value)}
          >
            <option value="USD">USD</option>
            <option value="IRR">{t("builder.customize.toman")}</option>
          </select>
        </label>
      </div>
    </div>
  );
}

function StepPrice({
  quote,
  isAuthenticated,
  locale,
  quoteRef,
}: {
  quote: QuoteView | null;
  isAuthenticated: boolean;
  locale: string;
  quoteRef: { id: string; secret: string } | null;
}) {
  const t = useTranslations();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function checkout() {
    if (!quoteRef) return;
    setBusy(true);
    setError(null);
    try {
      // Claim binds the anonymous quote to the workspace, then the order freezes it.
      if (!quote?.is_claimed) {
        await builderApi.claim(quoteRef.id, quoteRef.secret, locale as Locale);
      }
      const order = await checkoutApi.placeOrder(quoteRef.id, locale as Locale);
      quoteSession.clear();
      router.push(`/${locale}/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="font-medium">{t("builder.step.price")}</h2>

      {quote ? (
        <>
          <p className="text-sm text-muted">
            {t("builder.price.summary", {
              total: quote.total.formatted,
              monthly: quote.subtotal_recurring.formatted,
            })}
          </p>

          <div className="card space-y-3">
            <p className="text-sm font-medium">{t("builder.order.title")}</p>

            {!isAuthenticated ? (
              <>
                <p className="text-sm text-muted">{t("builder.order.signInFirst")}</p>
                <div className="flex flex-wrap gap-2">
                  <Link href={`/${locale}/register`} className="btn-primary">
                    {t("builder.order.createAccount")}
                  </Link>
                  <Link href={`/${locale}/login`} className="btn-ghost">
                    {t("nav.login")}
                  </Link>
                </div>
              </>
            ) : (
              <button
                type="button"
                className="btn-primary"
                disabled={busy || !quoteRef}
                onClick={checkout}
              >
                {busy ? t("common.loading") : t("builder.order.continue")}
              </button>
            )}

            {error ? (
              <p role="alert" className="text-sm text-red-500">
                {error}
              </p>
            ) : null}
          </div>
        </>
      ) : (
        <p className="text-sm text-muted">{t("builder.price.empty")}</p>
      )}
    </div>
  );
}
