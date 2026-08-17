/** Support tickets — the fallback for what the dashboard can't do yet (Phase 6). */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";

export type TicketStatus =
  | "OPEN"
  | "IN_PROGRESS"
  | "WAITING_FOR_CUSTOMER"
  | "RESOLVED"
  | "CLOSED";

export interface SupportAttachmentView {
  id: number;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  url: string;
  created_at: string;
}

export interface SupportMessageView {
  id: number;
  author_type: "CUSTOMER" | "STAFF";
  author_email: string | null;
  body: string;
  attachments: SupportAttachmentView[];
  created_at: string;
}

export interface SupportTicketView {
  id: string;
  bot: string | null;
  subject: string;
  status: TicketStatus;
  priority: "LOW" | "NORMAL" | "HIGH" | "URGENT";
  created_by_email: string | null;
  last_reply_at: string | null;
  created_at: string;
  messages?: SupportMessageView[];
}

export const supportApi = {
  list: (locale: Locale) => apiFetch<SupportTicketView[]>("/support/tickets/", { locale }),

  get: (id: string, locale: Locale) =>
    apiFetch<SupportTicketView>(`/support/tickets/${id}/`, { locale }),

  create: (payload: { subject: string; body: string; bot?: string }, locale: Locale) =>
    apiFetch<SupportTicketView>("/support/tickets/", {
      method: "POST",
      body: payload,
      locale,
    }),

  reply: (id: string, body: string, locale: Locale) =>
    apiFetch<SupportTicketView>(`/support/tickets/${id}/reply/`, {
      method: "POST",
      body: { body },
      locale,
    }),

  close: (id: string, locale: Locale) =>
    apiFetch<SupportTicketView>(`/support/tickets/${id}/close/`, { method: "POST", locale }),
};
