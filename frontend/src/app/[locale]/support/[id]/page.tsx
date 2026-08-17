"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SupportStatusBadge } from "@/components/support-status";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { supportApi, type SupportTicketView } from "@/lib/support";

export default function SupportDetailPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const { user, loading } = useAuth();

  const [ticket, setTicket] = useState<SupportTicketView | null>(null);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!params?.id) return;
    supportApi
      .get(params.id, locale)
      .then(setTicket)
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }, [params?.id, locale, t]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function sendReply(event: React.FormEvent) {
    event.preventDefault();
    if (!ticket) return;
    setBusy(true);
    setError(null);
    try {
      setTicket(await supportApi.reply(ticket.id, reply, locale));
      setReply("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function closeTicket() {
    if (!ticket) return;
    setBusy(true);
    try {
      setTicket(await supportApi.close(ticket.id, locale));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;
  if (error && !ticket) return <p className="text-sm text-red-500">{error}</p>;
  if (!ticket) return <p className="text-muted">{t("common.loading")}</p>;

  const isOpen = ticket.status !== "CLOSED";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href={`/${locale}/support`} className="text-xs text-muted hover:text-ink">
            ← {t("support.title")}
          </Link>
          <h1 className="text-2xl font-semibold">{ticket.subject}</h1>
        </div>
        <SupportStatusBadge status={ticket.status} />
      </div>

      <section className="space-y-3">
        {(ticket.messages ?? []).map((message) => (
          <div
            key={message.id}
            className={`card space-y-1 ${
              message.author_type === "STAFF" ? "border-accent/40" : ""
            }`}
          >
            <div className="flex items-center justify-between gap-3 text-xs text-muted">
              <span>
                {message.author_type === "STAFF" ? t("support.staff") : t("support.you")}
              </span>
              <span>{new Date(message.created_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}</span>
            </div>
            <p className="whitespace-pre-wrap text-sm">{message.body}</p>
            {message.attachments.length > 0 ? (
              <div className="flex flex-wrap gap-2 pt-1">
                {message.attachments.map((attachment) => (
                  <a
                    key={attachment.id}
                    href={attachment.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-accent"
                  >
                    {attachment.original_filename}
                  </a>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </section>

      {isOpen ? (
        <form onSubmit={sendReply} className="card space-y-3">
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("support.reply")}</span>
            <textarea
              className="field"
              rows={3}
              value={reply}
              onChange={(event) => setReply(event.target.value)}
              required
            />
          </label>
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className="btn-primary">
              {busy ? t("common.loading") : t("support.send")}
            </button>
            <button type="button" onClick={closeTicket} disabled={busy} className="btn-ghost">
              {t("support.close")}
            </button>
          </div>
        </form>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      ) : null}
    </div>
  );
}
