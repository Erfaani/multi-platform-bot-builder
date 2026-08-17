"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { aiApi, type AiUsageSummary, type KnowledgeDocumentView } from "@/lib/ai";

export function AiPanel({ botId, hasKnowledgeBase }: { botId: string; hasKnowledgeBase: boolean }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [instructions, setInstructions] = useState("");
  const [budget, setBudget] = useState("");
  const [usage, setUsage] = useState<AiUsageSummary | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocumentView[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState(false);
  const [busy, setBusy] = useState(false);

  function load() {
    aiApi.configuration(botId, locale).then((config) => {
      setInstructions(config.custom_instructions);
      setBudget(config.monthly_token_budget === null ? "" : String(config.monthly_token_budget));
    });
    aiApi.usage(botId, locale).then((data) => setUsage(data.summary));
    if (hasKnowledgeBase) aiApi.documents(botId, locale).then(setDocuments);
  }

  useEffect(load, [botId, locale, hasKnowledgeBase]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveConfiguration(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSavedMessage(false);
    try {
      await aiApi.updateConfiguration(
        botId,
        {
          custom_instructions: instructions,
          monthly_token_budget: budget.trim() === "" ? null : Number(budget),
        },
        locale,
      );
      setSavedMessage(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function addDocument(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await aiApi.createDocument(botId, title, content, locale);
      setTitle("");
      setContent("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function removeDocument(documentId: string) {
    try {
      await aiApi.deleteDocument(botId, documentId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  return (
    <section className="card space-y-5">
      <h2 className="font-medium">{t("bot.ai.title")}</h2>
      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <form onSubmit={saveConfiguration} className="space-y-2">
        <label className="block text-sm font-medium text-muted">{t("bot.ai.instructionsLabel")}</label>
        <textarea
          className="field"
          rows={3}
          maxLength={4000}
          placeholder={t("bot.ai.instructionsPlaceholder")}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <label className="block text-sm font-medium text-muted">{t("bot.ai.budgetLabel")}</label>
        <input
          className="field w-40"
          type="number"
          min={0}
          placeholder={t("bot.ai.budgetPlaceholder")}
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
        {savedMessage ? <p className="text-sm text-green-600">{t("bot.ai.saved")}</p> : null}
        <div>
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? t("common.loading") : t("common.save")}
          </button>
        </div>
      </form>

      {usage ? (
        <p className="text-sm text-muted border-t border-line pt-3">
          {t("bot.ai.usage", { used: usage.used_tokens, budget: usage.budget })}
        </p>
      ) : null}

      {hasKnowledgeBase ? (
        <div className="space-y-3 border-t border-line pt-4">
          <h3 className="text-sm font-medium text-muted">{t("bot.ai.knowledgeBase")}</h3>

          {documents.length === 0 ? (
            <p className="text-sm text-muted">{t("bot.ai.noDocuments")}</p>
          ) : (
            <ul className="space-y-2">
              {documents.map((doc) => (
                <li key={doc.id} className="flex items-center justify-between gap-2 rounded-lg border border-line p-3 text-sm">
                  <span>
                    {doc.title} · {t(`bot.ai.status.${doc.status}`)} · {doc.chunk_count}
                  </span>
                  <button type="button" className="text-red-500" onClick={() => removeDocument(doc.id)}>
                    {t("common.delete")}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <form onSubmit={addDocument} className="space-y-2">
            <input
              className="field"
              placeholder={t("bot.ai.documentTitlePlaceholder")}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
            <textarea
              className="field"
              rows={4}
              placeholder={t("bot.ai.documentContentPlaceholder")}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
            />
            <button type="submit" className="btn-secondary">
              {t("bot.ai.addDocument")}
            </button>
          </form>
        </div>
      ) : null}
    </section>
  );
}
