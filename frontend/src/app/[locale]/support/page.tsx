"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SupportStatusBadge } from "@/components/support-status";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { supportApi, type SupportTicketView } from "@/lib/support";

export default function SupportListPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const { user, loading } = useAuth();

  const [tickets, setTickets] = useState<SupportTicketView[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    supportApi
      .list(locale)
      .then(setTickets)
      .catch(() => setError(t("error.network")));
  }, [locale, t]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const ticket = await supportApi.create({ subject, body }, locale);
      router.push(`/${locale}/support/${ticket.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t("support.title")}</h1>
        <button type="button" onClick={() => setShowForm((v) => !v)} className="btn-primary">
          {t("support.newTicket")}
        </button>
      </div>

      {showForm ? (
        <form onSubmit={create} className="card space-y-3">
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("support.subject")}</span>
            <input
              className="field"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              required
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("support.message")}</span>
            <textarea
              className="field"
              rows={4}
              value={body}
              onChange={(event) => setBody(event.target.value)}
              required
            />
          </label>
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? t("common.loading") : t("support.submit")}
          </button>
        </form>
      ) : null}

      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      {tickets.length === 0 ? (
        <p className="text-sm text-muted">{t("support.empty")}</p>
      ) : (
        <ul className="space-y-2">
          {tickets.map((ticket) => (
            <li key={ticket.id}>
              <Link
                href={`/${locale}/support/${ticket.id}`}
                className="card flex items-center justify-between gap-3 transition hover:border-accent"
              >
                <span>
                  <span className="block text-sm font-medium">{ticket.subject}</span>
                  <span className="block text-xs text-muted">
                    {ticket.last_reply_at
                      ? new Date(ticket.last_reply_at).toLocaleDateString(
                          locale === "fa" ? "fa-IR" : "en-US",
                        )
                      : ""}
                  </span>
                </span>
                <SupportStatusBadge status={ticket.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
