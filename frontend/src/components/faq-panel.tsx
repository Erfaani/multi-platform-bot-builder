"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { botsApi, type FaqEntryView } from "@/lib/bots";

export function FaqPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [entries, setEntries] = useState<FaqEntryView[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editQuestion, setEditQuestion] = useState("");
  const [editAnswer, setEditAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    botsApi
      .faq(botId, locale)
      .then(setEntries)
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }

  useEffect(load, [botId, locale, t]);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await botsApi.createFaq(botId, { question, answer }, locale);
      setQuestion("");
      setAnswer("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  function startEdit(entry: FaqEntryView) {
    setEditingId(entry.id);
    setEditQuestion(entry.question);
    setEditAnswer(entry.answer);
  }

  async function saveEdit(id: number) {
    setBusy(true);
    setError(null);
    try {
      await botsApi.updateFaq(botId, id, { question: editQuestion, answer: editAnswer }, locale);
      setEditingId(null);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    setBusy(true);
    try {
      await botsApi.deleteFaq(botId, id, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{t("bot.faq.title")}</h2>
      <p className="text-sm text-muted">{t("bot.faq.hint")}</p>

      <ul className="space-y-2">
        {entries.map((entry) => (
          <li key={entry.id} className="rounded-lg border border-line p-3 text-sm">
            {editingId === entry.id ? (
              <div className="space-y-2">
                <input
                  className="field"
                  value={editQuestion}
                  onChange={(e) => setEditQuestion(e.target.value)}
                />
                <textarea
                  className="field"
                  rows={2}
                  value={editAnswer}
                  onChange={(e) => setEditAnswer(e.target.value)}
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => saveEdit(entry.id)}
                    disabled={busy}
                    className="btn-primary"
                  >
                    {t("common.save")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    className="btn-ghost"
                  >
                    {t("common.cancel")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-start justify-between gap-3">
                  <p className="font-medium">{entry.question}</p>
                  <div className="flex shrink-0 gap-2 text-xs">
                    <button type="button" onClick={() => startEdit(entry)} className="text-accent">
                      {t("bot.faq.edit")}
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(entry.id)}
                      className="text-red-500"
                    >
                      {t("bot.faq.delete")}
                    </button>
                  </div>
                </div>
                <p className="text-muted">{entry.answer}</p>
              </div>
            )}
          </li>
        ))}
        {entries.length === 0 ? <p className="text-sm text-muted">{t("bot.faq.empty")}</p> : null}
      </ul>

      <form onSubmit={add} className="space-y-2 border-t border-line pt-3">
        <input
          className="field"
          placeholder={t("bot.faq.questionPlaceholder")}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          required
        />
        <textarea
          className="field"
          rows={2}
          placeholder={t("bot.faq.answerPlaceholder")}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          required
        />
        {error ? <p className="text-sm text-red-500">{error}</p> : null}
        <button type="submit" disabled={busy} className="btn-primary">
          {t("bot.faq.add")}
        </button>
      </form>
    </section>
  );
}
