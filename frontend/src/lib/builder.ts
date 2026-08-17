/**
 * Builder API types and calls.
 *
 * Note what is absent: nothing here ever sends a price. The client describes a
 * configuration and the server returns what it costs (spec §12, §61.2).
 */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";

export interface MoneyView {
  amount_minor: number;
  currency: string;
  formatted: string;
}

export interface PlatformOption {
  slug: string;
  name: string;
  capabilities_verified: boolean;
}

export interface TemplateFeatureRef {
  slug: string;
  is_default: boolean;
  is_required: boolean;
  sort_order: number;
}

export interface BusinessTemplate {
  id: string;
  slug: string;
  icon: string;
  name: string;
  description: string;
  features: TemplateFeatureRef[];
  default_features: string[];
  required_features: string[];
}

export interface PlatformAvailability {
  available: boolean;
  reason: string;
  note: string;
}

export interface FeatureItem {
  id: string;
  slug: string;
  category: string;
  icon: string;
  name: string;
  description: string;
  requires: string[];
  always_on: boolean;
  platforms: Record<string, PlatformAvailability>;
  sort_order: number;
}

export interface QuoteItemView {
  price_key: string;
  label: string;
  feature_slug: string;
  quantity: number;
  billing_kind: "ONE_TIME" | "RECURRING_MONTHLY";
  unit_amount: MoneyView;
  amount: MoneyView;
}

export interface QuoteView {
  id: string;
  template: string;
  platforms: string[];
  selected_features: string[];
  resolved_features: string[];
  business_draft: Record<string, unknown>;
  currency: string;
  items: QuoteItemView[];
  subtotal_once: MoneyView;
  subtotal_recurring: MoneyView;
  total: MoneyView;
  is_claimed: boolean;
  is_expired: boolean;
  expires_at: string;
  auto_added_features?: string[];
  session_secret?: string;
}

export interface PreviewMessage {
  text: string;
  buttons: string[][];
  layout: "inline" | "reply" | "numbered" | "none";
  expects: string | null;
  notes: string[];
}

export interface PreviewScreen {
  key: string;
  title: string;
  user_says: string | null;
  message: PreviewMessage;
}

export interface PlatformPreview {
  platform: string;
  display_name: string;
  capabilities_verified: boolean;
  screens: PreviewScreen[];
  warnings: string[];
}

export interface BuildQuotePayload {
  template: string;
  platforms: string[];
  features: string[];
  currency?: string;
  country?: string;
  business?: Record<string, unknown>;
}

const SESSION_KEY = "bb.quote";

export const quoteSession = {
  read(): { id: string; secret: string } | null {
    if (typeof window === "undefined") return null;
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },
  write(id: string, secret: string) {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ id, secret }));
  },
  clear() {
    sessionStorage.removeItem(SESSION_KEY);
  },
};

export const builderApi = {
  platforms: (locale: Locale) =>
    apiFetch<PlatformOption[]>("/platforms/", { auth: false, locale }),

  templates: (locale: Locale) =>
    apiFetch<BusinessTemplate[]>("/templates/", { auth: false, locale }),

  features: (locale: Locale) =>
    apiFetch<FeatureItem[]>("/features/", { auth: false, locale }),

  createQuote: (payload: BuildQuotePayload, locale: Locale) =>
    apiFetch<QuoteView>("/quotes/", {
      method: "POST",
      body: payload,
      auth: false,
      locale,
    }),

  updateQuote: (
    id: string,
    secret: string,
    payload: BuildQuotePayload,
    locale: Locale,
  ) =>
    apiFetch<QuoteView>(`/quotes/${id}/`, {
      method: "PUT",
      body: payload,
      auth: false,
      locale,
      quoteSession: secret,
    }),

  preview: (id: string, secret: string, locale: Locale) =>
    apiFetch<{ quote: string; platforms: PlatformPreview[] }>(
      `/quotes/${id}/preview/`,
      { auth: false, locale, quoteSession: secret },
    ),

  claim: (id: string, secret: string, locale: Locale) =>
    apiFetch<QuoteView>(`/quotes/${id}/claim/`, {
      method: "POST",
      locale,
      quoteSession: secret,
    }),
};
