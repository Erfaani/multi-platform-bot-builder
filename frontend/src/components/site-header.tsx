"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { checkoutApi } from "@/lib/checkout";
import { useAuth } from "@/lib/auth";
import { LanguageSwitcher } from "./language-switcher";

function NotificationBell() {
  const t = useTranslations();
  const { locale } = useIntl();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    const poll = () => {
      checkoutApi
        .unreadCount()
        .then((res) => setUnread(res.unread))
        .catch(() => {});
    };
    poll();
    const timer = setInterval(poll, 30000);
    return () => clearInterval(timer);
  }, []);

  return (
    <Link
      href={`/${locale}/notifications`}
      className="relative text-muted hover:text-ink"
      aria-label={t("notifications.title")}
    >
      {t("notifications.title")}
      {unread > 0 ? (
        <span className="absolute -end-2 -top-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      ) : null}
    </Link>
  );
}

export function SiteHeader() {
  const t = useTranslations();
  const { locale } = useIntl();
  const { user, logout, loading } = useAuth();

  return (
    <header className="flex items-center justify-between gap-4 border-b border-line py-4">
      <Link href={`/${locale}`} className="font-semibold">
        {t("brand.name")}
      </Link>

      <nav className="flex flex-wrap items-center gap-3 text-sm">
        <Link href={`/${locale}/templates`} className="hidden text-muted hover:text-ink sm:inline">
          {t("nav.templates")}
        </Link>
        <Link href={`/${locale}/features`} className="hidden text-muted hover:text-ink sm:inline">
          {t("nav.features")}
        </Link>
        <Link href={`/${locale}/pricing`} className="hidden text-muted hover:text-ink sm:inline">
          {t("nav.pricing")}
        </Link>
        <Link href={`/${locale}/build`} className="text-accent hover:opacity-80">
          {t("nav.build")}
        </Link>

        <LanguageSwitcher />

        {loading ? null : user ? (
          <>
            <Link href={`/${locale}/dashboard`} className="text-muted hover:text-ink">
              {t("nav.dashboard")}
            </Link>
            <Link href={`/${locale}/support`} className="hidden text-muted hover:text-ink sm:inline">
              {t("nav.support")}
            </Link>
            <Link href={`/${locale}/settings`} className="hidden text-muted hover:text-ink sm:inline">
              {t("nav.settings")}
            </Link>
            <NotificationBell />
            <button type="button" onClick={logout} className="text-muted hover:text-ink">
              {t("nav.logout")}
            </button>
          </>
        ) : (
          <>
            <Link href={`/${locale}/login`} className="text-muted hover:text-ink">
              {t("nav.login")}
            </Link>
            <Link href={`/${locale}/register`} className="btn-primary">
              {t("nav.register")}
            </Link>
          </>
        )}
      </nav>
    </header>
  );
}
