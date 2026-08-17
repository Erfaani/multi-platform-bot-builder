"use client";

import { useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { botsApi, type BotInstance } from "@/lib/bots";

/**
 * The guided BotFather flow (ADR-0002 tier B).
 *
 * Telegram has no API to create a bot, so this ~60-second walkthrough is the one manual
 * step. The token is submitted once, validated, encrypted, and never shown again.
 */
export function TokenHandoff({
  botId,
  instance,
  onDone,
}: {
  botId: string;
  instance: BotInstance;
  onDone: () => void;
}) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await botsApi.submitToken(botId, instance.id, token.trim(), locale);
      setToken("");
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  const steps = ["open", "newbot", "name", "username", "copy"] as const;

  return (
    <section className="card space-y-4">
      <div>
        <h3 className="font-medium">{t("handoff.title")}</h3>
        <p className="text-sm text-muted">{t("handoff.intro")}</p>
      </div>

      <ol className="space-y-2 text-sm">
        {steps.map((step, index) => (
          <li key={step} className="flex gap-3">
            <span className="text-accent">{index + 1}</span>
            <span className="text-muted">{t(`handoff.step.${step}`)}</span>
          </li>
        ))}
      </ol>

      <p className="rounded-lg border border-line p-3 text-xs text-muted">
        {t("handoff.privacy")}
      </p>

      <form onSubmit={submit} className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("handoff.field")}</span>
          <input
            className="field"
            dir="ltr"
            required
            autoComplete="off"
            placeholder="123456789:AA..."
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
        </label>

        {error ? (
          <p role="alert" className="text-sm text-red-500">
            {error}
          </p>
        ) : null}

        <button type="submit" disabled={busy || !token.trim()} className="btn-primary">
          {busy ? t("common.loading") : t("handoff.submit")}
        </button>
      </form>
    </section>
  );
}
