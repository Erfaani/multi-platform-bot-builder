"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { useAuth } from "@/lib/auth";
import { checkoutApi, type NotificationView } from "@/lib/checkout";

export default function NotificationsPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const { user, loading } = useAuth();

  const [items, setItems] = useState<NotificationView[]>([]);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    checkoutApi
      .notifications(locale)
      .then((page) => setItems(page.results))
      .catch(() => setFailed(true));
  }, [locale]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function open(item: NotificationView) {
    if (!item.is_read) {
      setItems((prev) => prev.map((n) => (n.id === item.id ? { ...n, is_read: true } : n)));
      checkoutApi.markRead(item.id).catch(() => load());
    }
    if (item.link) router.push(item.link);
  }

  async function markAll() {
    setBusy(true);
    try {
      await checkoutApi.markAllRead();
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;

  const hasUnread = items.some((item) => !item.is_read);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t("notifications.title")}</h1>
        {hasUnread ? (
          <button type="button" onClick={markAll} disabled={busy} className="btn-ghost">
            {t("notifications.markAllRead")}
          </button>
        ) : null}
      </div>

      {failed ? <p className="text-sm text-red-500">{t("error.network")}</p> : null}

      {items.length === 0 ? (
        <p className="text-sm text-muted">{t("notifications.empty")}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => open(item)}
                className={`card flex w-full items-start justify-between gap-3 text-start transition hover:border-accent ${
                  item.is_read ? "" : "border-accent/60"
                }`}
              >
                <span className="space-y-1">
                  <span className="flex items-center gap-2">
                    {!item.is_read ? <span className="h-2 w-2 rounded-full bg-accent" /> : null}
                    <span className="text-sm font-medium">{item.title}</span>
                  </span>
                  <span className="block text-sm text-muted">{item.body}</span>
                </span>
                <span className="shrink-0 text-xs text-muted">
                  {new Date(item.created_at).toLocaleDateString(
                    locale === "fa" ? "fa-IR" : "en-US",
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <Link href={`/${locale}/dashboard`} className="text-xs text-muted hover:text-ink">
        ← {t("dashboard.title")}
      </Link>
    </div>
  );
}
