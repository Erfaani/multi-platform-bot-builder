"use client";

import { useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { botsApi } from "@/lib/bots";

export function BroadcastPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [text, setText] = useState("");
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSent(null);
    try {
      const result = await botsApi.broadcast(botId, text, locale);
      setSent(result.recipients);
      setText("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{t("bot.broadcast.title")}</h2>
      <p className="text-sm text-muted">{t("bot.broadcast.hint")}</p>

      <form onSubmit={send} className="space-y-2">
        <textarea
          className="field"
          rows={3}
          maxLength={2000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          required
        />
        {error ? <p className="text-sm text-red-500">{error}</p> : null}
        {sent !== null ? <p className="text-sm text-green-600">{t("bot.broadcast.sent", { count: sent })}</p> : null}
        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? t("common.loading") : t("bot.broadcast.send")}
        </button>
      </form>
    </section>
  );
}
