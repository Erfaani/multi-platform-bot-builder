/** Bots, provisioning progress and the guided token handoff. */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";
import type { MoneyView, QuoteView } from "./builder";

export interface BotInstance {
  id: string;
  platform: string;
  status: string;
  username: string;
  display_name: string;
  link: string;
  acquisition_mode: "POOL" | "TOKEN_HANDOFF" | "MTPROTO";
  needs_token: boolean;
  webhook_set_at: string | null;
  last_update_at: string | null;
}

export interface ProvisioningStep {
  slug: string;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED" | "BLOCKED";
}

export interface ProvisioningProgress {
  status: string;
  strategy: string;
  error_code: string;
  steps: ProvisioningStep[];
}

export interface SubscriptionView {
  status: "ACTIVE" | "GRACE_PERIOD" | "SUSPENDED";
  monthly_amount: MoneyView;
  current_period_end: string;
  grace_period_ends_at: string | null;
}

export interface BotView {
  id: string;
  name: string;
  status: string;
  template: string;
  default_locale: string;
  timezone: string;
  currency: string;
  instances: BotInstance[];
  features: string[];
  provisioning: ProvisioningProgress | null;
  subscription: SubscriptionView | null;
  last_activity_at: string | null;
  created_at: string;
}

interface Paginated<T> {
  count: number;
  results: T[];
}

export interface BusinessProfileView {
  display_name: string;
  description: string;
  phone: string;
  secondary_phone: string;
  email: string;
  website: string;
  address: string;
  city: string;
  working_hours_text: string;
}

export interface FaqEntryView {
  id: number;
  question: string;
  answer: string;
  category: string;
  sort_order: number;
  is_active: boolean;
  source: "MANUAL" | "AI_GENERATED";
}

export interface AvailableFeatureView {
  slug: string;
  name: string;
  description: string;
  icon: string;
  setup_amount: MoneyView;
  monthly_amount: MoneyView;
}

export interface AnalyticsDailyPoint {
  date: string;
  count: number;
}

export interface AnalyticsSummaryView {
  total_contacts: number;
  new_contacts_7d: number;
  messages_7d: number;
  daily_messages: AnalyticsDailyPoint[];
}

export interface AppointmentServiceView {
  id: number;
  name: string;
  description: string;
  duration_minutes: number;
  buffer_minutes: number;
  price: MoneyView | null;
  is_active: boolean;
  sort_order: number;
}

export interface StaffMemberView {
  id: number;
  name: string;
  service_ids: number[];
  is_active: boolean;
  sort_order: number;
}

export interface SlotView {
  starts_at: string;
  ends_at: string;
}

export interface AppointmentView {
  id: string;
  service: string;
  staff: string;
  contact_name: string;
  starts_at: string;
  ends_at: string;
  business_timezone: string;
  status: "CONFIRMED" | "CANCELLED" | "COMPLETED" | "NO_SHOW";
  cancellation_reason: string;
  created_at: string;
}

export const botsApi = {
  list: (locale: Locale) => apiFetch<Paginated<BotView>>("/bots/", { locale }),

  get: (id: string, locale: Locale) => apiFetch<BotView>(`/bots/${id}/`, { locale }),

  updateConfiguration: (
    id: string,
    payload: { name?: string; welcome_message?: string; default_locale?: string },
    locale: Locale,
  ) =>
    apiFetch<BotView>(`/bots/${id}/configuration/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  submitToken: (botId: string, instanceId: string, token: string, locale: Locale) =>
    apiFetch<BotView>(`/bots/${botId}/instances/${instanceId}/token/`, {
      method: "POST",
      body: { token },
      locale,
    }),

  businessProfile: (id: string, locale: Locale) =>
    apiFetch<BusinessProfileView>(`/bots/${id}/business-profile/`, { locale }),

  updateBusinessProfile: (id: string, payload: Partial<BusinessProfileView>, locale: Locale) =>
    apiFetch<BusinessProfileView>(`/bots/${id}/business-profile/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  faq: (id: string, locale: Locale) => apiFetch<FaqEntryView[]>(`/bots/${id}/faq/`, { locale }),

  createFaq: (
    id: string,
    payload: { question: string; answer: string; sort_order?: number },
    locale: Locale,
  ) =>
    apiFetch<FaqEntryView>(`/bots/${id}/faq/`, { method: "POST", body: payload, locale }),

  updateFaq: (
    id: string,
    faqId: number,
    payload: Partial<Pick<FaqEntryView, "question" | "answer" | "sort_order" | "is_active">>,
    locale: Locale,
  ) =>
    apiFetch<FaqEntryView>(`/bots/${id}/faq/${faqId}/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  deleteFaq: (id: string, faqId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${id}/faq/${faqId}/`, { method: "DELETE", locale }),

  availableFeatures: (id: string, locale: Locale) =>
    apiFetch<AvailableFeatureView[]>(`/bots/${id}/available-features/`, { locale }),

  addonQuote: (id: string, features: string[], locale: Locale) =>
    apiFetch<QuoteView>(`/bots/${id}/addon-quotes/`, {
      method: "POST",
      body: { features },
      locale,
    }),

  analytics: (id: string, locale: Locale) =>
    apiFetch<AnalyticsSummaryView>(`/bots/${id}/analytics/`, { locale }),

  appointmentServices: (id: string, locale: Locale) =>
    apiFetch<AppointmentServiceView[]>(`/bots/${id}/appointment-services/`, { locale }),

  createAppointmentService: (
    id: string,
    payload: { name: string; duration_minutes: number; buffer_minutes?: number },
    locale: Locale,
  ) =>
    apiFetch<AppointmentServiceView>(`/bots/${id}/appointment-services/`, {
      method: "POST",
      body: payload,
      locale,
    }),

  updateAppointmentService: (
    id: string,
    serviceId: number,
    payload: Partial<Pick<AppointmentServiceView, "name" | "duration_minutes" | "buffer_minutes" | "is_active">>,
    locale: Locale,
  ) =>
    apiFetch<AppointmentServiceView>(`/bots/${id}/appointment-services/${serviceId}/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  deleteAppointmentService: (id: string, serviceId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${id}/appointment-services/${serviceId}/`, { method: "DELETE", locale }),

  staffMembers: (id: string, locale: Locale) =>
    apiFetch<StaffMemberView[]>(`/bots/${id}/staff/`, { locale }),

  createStaffMember: (id: string, payload: { name: string }, locale: Locale) =>
    apiFetch<StaffMemberView>(`/bots/${id}/staff/`, { method: "POST", body: payload, locale }),

  deleteStaffMember: (id: string, staffId: number, locale: Locale) =>
    apiFetch<void>(`/bots/${id}/staff/${staffId}/`, { method: "DELETE", locale }),

  appointments: (id: string, locale: Locale) =>
    apiFetch<AppointmentView[]>(`/bots/${id}/appointments/`, { locale }),

  cancelAppointment: (id: string, appointmentId: string, reason: string, locale: Locale) =>
    apiFetch<AppointmentView>(`/bots/${id}/appointments/${appointmentId}/cancel/`, {
      method: "POST",
      body: { reason },
      locale,
    }),

  broadcast: (id: string, text: string, locale: Locale) =>
    apiFetch<{ recipients: number }>(`/bots/${id}/broadcast/`, { method: "POST", body: { text }, locale }),
};
