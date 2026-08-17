/** Leads captured from a bot conversation, and customer feedback (Phase 7 CRM). */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";

export type LeadStatus = "NEW" | "CONTACTED" | "QUALIFIED" | "WON" | "LOST";

export interface ContactNoteView {
  id: number;
  author_email: string | null;
  body: string;
  created_at: string;
}

export interface LeadView {
  id: string;
  source: "CONTACT_FORM" | "CONSULTATION_REQUEST" | "MANUAL";
  status: LeadStatus;
  message: string;
  phone: string;
  contact_name: string;
  assigned_to_email: string | null;
  notes: ContactNoteView[];
  tags: string[];
  created_at: string;
}

export interface FeedbackView {
  id: number;
  rating: number;
  comment: string;
  contact_name: string;
  created_at: string;
}

export const crmApi = {
  leads: (botId: string, locale: Locale) => apiFetch<LeadView[]>(`/bots/${botId}/leads/`, { locale }),

  updateLead: (botId: string, leadId: string, payload: { status?: LeadStatus }, locale: Locale) =>
    apiFetch<LeadView>(`/bots/${botId}/leads/${leadId}/`, { method: "PATCH", body: payload, locale }),

  addNote: (botId: string, leadId: string, body: string, locale: Locale) =>
    apiFetch<LeadView>(`/bots/${botId}/leads/${leadId}/notes/`, {
      method: "POST",
      body: { body },
      locale,
    }),

  tagLead: (botId: string, leadId: string, tag: string, locale: Locale) =>
    apiFetch<LeadView>(`/bots/${botId}/leads/${leadId}/tags/`, { method: "POST", body: { tag }, locale }),

  feedback: (botId: string, locale: Locale) => apiFetch<FeedbackView[]>(`/bots/${botId}/feedback/`, { locale }),
};
