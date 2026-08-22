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
  type CollectItemField,
  type CollectSchema,
  type FeatureItem,
  type PlatformOption,
  type PlatformPreview,
  type QuoteView,
} from "@/lib/builder";
import { useAuth } from "@/lib/auth";
import { AppIcon } from "@/lib/icons";
import { localeCurrency } from "@/lib/format";
import { platformBrand } from "@/lib/platform-brand";
import { PlatformIcon } from "@/components/platform-icon";

/** Spec §8. Steps 8–9 (order, payment) arrive in Phase 3.
 *
 * Not every step is fixed: a "collect:<slug>" step is inserted for each selected
 * feature that declares a `collects` schema (dynamic configuration, Phase 10.5) — FAQ's
 * "enter your questions and answers" instead of a generic form, only shown when FAQ is
 * actually selected. `buildSteps()` computes the real, current list; this constant is
 * only the fixed part, before and after the dynamic middle.
 */
const BASE_STEPS = ["platform", "business_type", "features"] as const;
const TAIL_STEPS = ["business_info", "customize", "preview", "price"] as const;

type FixedStep = (typeof BASE_STEPS)[number] | (typeof TAIL_STEPS)[number];
type Step = FixedStep | `collect:${string}`;

function buildSteps(collectFeatures: FeatureItem[]): Step[] {
  return [
    ...BASE_STEPS,
    ...collectFeatures.map((feature): Step => `collect:${feature.slug}`),
    ...TAIL_STEPS,
  ];
}

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
  const { user, tenants, activeTenantId } = useAuth();

  const [step, setStep] = useState<Step>("platform");

  const [platforms, setPlatforms] = useState<PlatformOption[]>([]);
  const [templates, setTemplates] = useState<BusinessTemplate[]>([]);
  const [features, setFeatures] = useState<FeatureItem[]>([]);

  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [templateSlug, setTemplateSlug] = useState<string>("");
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);
  const [draft, setDraft] = useState<BusinessDraft>(EMPTY_DRAFT);

  // One entry per selected feature that declares a `collects` schema (FAQ's Q&A pairs,
  // and — Stage 3 — property/course content). Keyed by feature slug so switching a
  // feature off and back on does not lose what was already typed.
  const [featureConfig, setFeatureConfig] = useState<Record<string, Record<string, string>[]>>({});

  const collectFeatures = useMemo(
    () =>
      selectedFeatures
        .map((slug) => features.find((item) => item.slug === slug))
        .filter((item): item is FeatureItem => Boolean(item?.collects)),
    [selectedFeatures, features],
  );

  const steps = useMemo(() => buildSteps(collectFeatures), [collectFeatures]);
  const stepIndex = Math.max(steps.indexOf(step), 0);

  // A feature can be deselected (or a platform choice can drop it, see `blockedFeatures`
  // below) while its collect step is the one on screen — land somewhere still valid
  // rather than showing a step that no longer exists.
  useEffect(() => {
    if (!steps.includes(step)) setStep("features");
  }, [steps, step]);

  // Currency defaults from the site locale (fa -> IRR, en -> USD) and updates the
  // instant the locale changes — it must never sit frozen at whatever it was when the
  // customer landed, all the way through pricing/checkout. A signed-in visitor's own
  // saved preference (or their workspace default) wins over the locale default; an
  // explicit manual choice this session wins over both, until they change locale again.
  const [currency, setCurrencyState] = useState<string>(() => localeCurrency(locale));
  const currencyOverridden = useRef(false);

  const activeTenant = useMemo(
    () => tenants.find((item) => item.id === activeTenantId) ?? null,
    [tenants, activeTenantId],
  );

  useEffect(() => {
    if (currencyOverridden.current) return;
    setCurrencyState(user?.preferred_currency || activeTenant?.default_currency || localeCurrency(locale));
  }, [locale, user?.preferred_currency, activeTenant?.default_currency]);

  function setCurrency(next: string) {
    currencyOverridden.current = true;
    setCurrencyState(next);
  }

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
        business: { ...draft, feature_config: featureConfig } as unknown as Record<string, unknown>,
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
  }, [templateSlug, selectedPlatforms, selectedFeatures, currency, draft, featureConfig, locale, t]);

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
        // Collect steps (FAQ, etc.) are optional — content can always be added later
        // from the bot management panel, so an empty list must never block checkout.
        return true;
    }
  }, [step, selectedPlatforms, templateSlug, draft.name]);

  function stepLabel(name: Step): string {
    if (name.startsWith("collect:")) {
      const slug = name.slice("collect:".length);
      return features.find((item) => item.slug === slug)?.name ?? slug;
    }
    return t(`builder.step.${name}`);
  }

  function goTo(delta: 1 | -1) {
    const next = stepIndex + delta;
    if (next >= 0 && next < steps.length) setStep(steps[next]);
  }

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">{t("builder.title")}</h1>
          <CurrencyControl currency={currency} onChange={setCurrency} />
        </div>
        <ol className="flex flex-wrap gap-2 text-xs">
          {steps.map((name, index) => (
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
              {index + 1}. {stepLabel(name)}
            </li>
          ))}
          <li className="rounded-md border border-dashed border-line px-2 py-1 text-muted">
            {steps.length + 1}. {t("builder.step.order")}
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

          {step.startsWith("collect:")
            ? (() => {
                const slug = step.slice("collect:".length);
                const feature = collectFeatures.find((item) => item.slug === slug);
                if (!feature?.collects) return null;
                return (
                  <StepCollect
                    feature={feature}
                    schema={feature.collects}
                    items={featureConfig[slug] ?? []}
                    onChange={(items) =>
                      setFeatureConfig((current) => ({ ...current, [slug]: items }))
                    }
                  />
                );
              })()
            : null}

          {step === "customize" ? <StepCustomize draft={draft} onChange={setDraft} /> : null}

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
              onClick={() => goTo(-1)}
            >
              {t("builder.back")}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!canAdvance || stepIndex === steps.length - 1}
              onClick={() => goTo(1)}
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
          const brand = platformBrand(platform.slug);
          return (
            <button
              key={platform.slug}
              type="button"
              onClick={() => onToggle(platform.slug)}
              aria-pressed={active}
              className="card card-selectable flex items-start gap-3 text-start"
            >
              <span className="icon-badge" style={{ background: brand.bg }}>
                <PlatformIcon slug={platform.slug} size={20} />
              </span>
              <span>
                <span className="block font-medium">{platform.name}</span>
                {!platform.capabilities_verified ? (
                  <span className="block text-xs text-muted">
                    {t("builder.platform.provisional")}
                  </span>
                ) : null}
              </span>
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
            className="card card-selectable flex items-start gap-3 text-start"
          >
            <span className="icon-badge bg-accent-soft text-accent">
              <AppIcon name={template.icon} size={20} />
            </span>
            <span>
              <span className="block font-medium">{template.name}</span>
              <span className="block text-sm text-muted">{template.description}</span>
            </span>
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
              className={`card card-selectable flex items-start justify-between gap-3 text-start ${
                isBlocked ? "opacity-50" : ""
              }`}
            >
              <span className="flex items-start gap-3">
                <span className="icon-badge bg-accent-soft text-accent">
                  <AppIcon name={feature.icon} size={18} />
                </span>
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
              </span>
              {active ? <AppIcon name="check" size={16} className="mt-1 shrink-0 text-accent" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Generic add/edit/delete list editor for any `CollectSchema` of `kind:
 * "repeatable_form"` — driven entirely by the fields the backend declares for the
 * selected feature, so a new feature that needs the same shape (Stage 3's properties,
 * courses) needs no new frontend code, only a new manifest. Mirrors
 * `components/faq-panel.tsx`'s UI exactly; this is its pre-purchase, local-state sibling
 * — nothing here calls the API, the whole list is submitted with the quote and
 * materialized into real rows once the order is placed (`apps.provisioning.saga`). */
function StepCollect({
  schema,
  items,
  onChange,
}: {
  feature: FeatureItem;
  schema: CollectSchema;
  items: Record<string, string>[];
  onChange: (items: Record<string, string>[]) => void;
}) {
  const t = useTranslations();
  const emptyDraft = useCallback(
    () => Object.fromEntries(schema.fields.map((field) => [field.key, ""])),
    [schema.fields],
  );
  const [draft, setDraftItem] = useState<Record<string, string>>(emptyDraft);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<Record<string, string>>(emptyDraft);

  const atMax = items.length >= schema.max_items;
  const isComplete = (candidate: Record<string, string>) =>
    schema.fields.every((field) => !field.required || candidate[field.key]?.trim());

  /** A `select` field's stored value is its raw option value ("SALE") — shown to the
   * customer as its translated label ("For sale"), never the raw code. */
  function displayValue(field: CollectItemField, value: string): string {
    if (field.kind !== "select") return value;
    const option = field.options.find((item) => item.value === value);
    return option ? t(option.label_key) : value;
  }

  function addItem(event: React.FormEvent) {
    event.preventDefault();
    if (atMax || !isComplete(draft)) return;
    onChange([...items, draft]);
    setDraftItem(emptyDraft());
  }

  function startEdit(index: number) {
    setEditingIndex(index);
    setEditDraft(items[index]);
  }

  function saveEdit() {
    if (editingIndex === null || !isComplete(editDraft)) return;
    onChange(items.map((item, index) => (index === editingIndex ? editDraft : item)));
    setEditingIndex(null);
  }

  function remove(index: number) {
    onChange(items.filter((_, i) => i !== index));
    if (editingIndex === index) setEditingIndex(null);
  }

  const [primaryField, ...restFields] = schema.fields;

  return (
    <div className="space-y-3">
      <h2 className="font-medium">{t(schema.title_key)}</h2>
      {schema.hint_key ? <p className="text-sm text-muted">{t(schema.hint_key)}</p> : null}

      <ul className="space-y-2">
        {items.map((item, index) => (
          <li key={index} className="rounded-lg border border-line p-3 text-sm">
            {editingIndex === index ? (
              <div className="space-y-2">
                {schema.fields.map((field) => (
                  <FieldInput
                    key={field.key}
                    field={field}
                    value={editDraft[field.key] ?? ""}
                    onChange={(value) => setEditDraft((cur) => ({ ...cur, [field.key]: value }))}
                  />
                ))}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={saveEdit}
                    disabled={!isComplete(editDraft)}
                    className="btn-primary"
                  >
                    {t("common.save")}
                  </button>
                  <button type="button" onClick={() => setEditingIndex(null)} className="btn-ghost">
                    {t("common.cancel")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-start justify-between gap-3">
                  <p className="font-medium">
                    {primaryField ? displayValue(primaryField, item[primaryField.key]) : ""}
                  </p>
                  <div className="flex shrink-0 gap-2 text-xs">
                    <button type="button" onClick={() => startEdit(index)} className="text-accent">
                      {t("bot.faq.edit")}
                    </button>
                    <button type="button" onClick={() => remove(index)} className="text-red-500">
                      {t("bot.faq.delete")}
                    </button>
                  </div>
                </div>
                {restFields
                  .filter((field) => item[field.key])
                  .map((field) => (
                    <p key={field.key} className="text-muted">
                      {displayValue(field, item[field.key])}
                    </p>
                  ))}
              </div>
            )}
          </li>
        ))}
        {items.length === 0 ? <p className="text-sm text-muted">{t("builder.collect.empty")}</p> : null}
      </ul>

      {atMax ? (
        <p className="text-xs text-muted">{t("builder.collect.maxReached")}</p>
      ) : (
        <form onSubmit={addItem} className="space-y-2 border-t border-line pt-3">
          {schema.fields.map((field) => (
            <FieldInput
              key={field.key}
              field={field}
              value={draft[field.key] ?? ""}
              onChange={(value) => setDraftItem((cur) => ({ ...cur, [field.key]: value }))}
            />
          ))}
          <button type="submit" disabled={!isComplete(draft)} className="btn-primary">
            {schema.add_label_key ? t(schema.add_label_key) : t("builder.collect.add")}
          </button>
        </form>
      )}

      <p className="text-xs text-muted">{t("builder.collect.optionalHint")}</p>
    </div>
  );
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: CollectItemField;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations();
  if (field.kind === "select") {
    return (
      <label className="block space-y-1">
        <span className="text-sm text-muted">{t(field.label_key)}</span>
        <select className="field" value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="" disabled>
            {t("builder.collect.selectPlaceholder")}
          </option>
          {field.options.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.label_key)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (field.kind === "textarea") {
    return (
      <label className="block space-y-1">
        <span className="text-sm text-muted">{t(field.label_key)}</span>
        <textarea
          className="field"
          rows={2}
          value={value}
          maxLength={field.max_length}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }
  return (
    <label className="block space-y-1">
      <span className="text-sm text-muted">{t(field.label_key)}</span>
      <input
        className="field"
        value={value}
        maxLength={field.max_length}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function StepCustomize({
  draft,
  onChange,
}: {
  draft: BusinessDraft;
  onChange: (draft: BusinessDraft) => void;
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

      <label className="block space-y-1 sm:max-w-xs">
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
    </div>
  );
}

/** Visible on every step — a currency shown or changed only at checkout is exactly the
 * bug this fixes (I18N.md / product feedback). Defaults from the site locale
 * (`localeCurrency`) and stays overridable, since a visitor may deliberately want prices
 * in a currency other than their locale's default. */
function CurrencyControl({
  currency,
  onChange,
}: {
  currency: string;
  onChange: (currency: string) => void;
}) {
  const t = useTranslations();
  return (
    <label className="flex items-center gap-2 text-xs text-muted">
      <span>{t("builder.customize.currency")}</span>
      <select
        className="field w-auto py-1"
        value={currency}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="USD">{t("builder.customize.usd")}</option>
        <option value="IRR">{t("builder.customize.toman")}</option>
      </select>
    </label>
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
