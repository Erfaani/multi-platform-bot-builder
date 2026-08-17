/** The AI assistant's configuration, knowledge-base documents, and usage (Phase 8). */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";

export interface AiConfigurationView {
  custom_instructions: string;
  monthly_token_budget: number | null;
}

export interface KnowledgeDocumentView {
  id: string;
  title: string;
  content_type: string;
  status: "PENDING" | "READY" | "FAILED";
  error_message: string;
  chunk_count: number;
  created_at: string;
}

export interface AiUsageSummary {
  used_tokens: number;
  budget: number;
  remaining: number;
}

export interface AiUsageRecordView {
  id: number;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  used_knowledge_base: boolean;
  created_at: string;
}

export interface AiUsageView {
  summary: AiUsageSummary;
  records: AiUsageRecordView[];
}

export const aiApi = {
  configuration: (botId: string, locale: Locale) =>
    apiFetch<AiConfigurationView>(`/bots/${botId}/ai-configuration/`, { locale }),

  updateConfiguration: (
    botId: string,
    payload: { custom_instructions?: string; monthly_token_budget?: number | null },
    locale: Locale,
  ) =>
    apiFetch<AiConfigurationView>(`/bots/${botId}/ai-configuration/`, {
      method: "PATCH",
      body: payload,
      locale,
    }),

  usage: (botId: string, locale: Locale) => apiFetch<AiUsageView>(`/bots/${botId}/ai-usage/`, { locale }),

  documents: (botId: string, locale: Locale) =>
    apiFetch<KnowledgeDocumentView[]>(`/bots/${botId}/ai-documents/`, { locale }),

  createDocument: (botId: string, title: string, content: string, locale: Locale) =>
    apiFetch<KnowledgeDocumentView>(`/bots/${botId}/ai-documents/`, {
      method: "POST",
      body: { title, content },
      locale,
    }),

  deleteDocument: (botId: string, documentId: string, locale: Locale) =>
    apiFetch<void>(`/bots/${botId}/ai-documents/${documentId}/`, { method: "DELETE", locale }),
};
