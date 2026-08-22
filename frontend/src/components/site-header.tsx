"use client";

import Link from "next/link";
import { Bot } from "lucide-react";
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
      className="relative text-sm font-medium text-white/70 hover:text-white"
      aria-label={t("notifications.title")}
    >
      {t("notifications.title")}
      {unread > 0 ? (
        <span className="absolute -end-2.5 -top-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-secondary px-1 text-[10px] font-semibold text-white">
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
    <header className="sticky top-0 z-20 bg-dark shadow-[0_1px_0_0_rgba(255,255,255,0.06)]">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
        <Link href={`/${locale}`} className="flex items-center gap-2.5">
          <span className="icon-badge bg-accent">
            <Bot className="h-5 w-5 text-white" strokeWidth={2.25} />
          </span>
          <span className="text-lg font-bold tracking-tight text-white">{t("brand.name")}</span>
        </Link>

        <nav className="flex flex-wrap items-center gap-1 text-sm">
          <Link
            href={`/${locale}/templates`}
            className="hidden rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white sm:inline-block"
          >
            {t("nav.templates")}
          </Link>
          <Link
            href={`/${locale}/features`}
            className="hidden rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white sm:inline-block"
          >
            {t("nav.features")}
          </Link>
          <Link
            href={`/${locale}/pricing`}
            className="hidden rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white sm:inline-block"
          >
            {t("nav.pricing")}
          </Link>
          <Link
            href={`/${locale}/build`}
            className="mx-1 inline-flex items-center justify-center rounded-full bg-accent px-4 py-1.5 font-semibold text-white shadow-sm transition hover:bg-accent-strong"
          >
            {t("nav.build")}
          </Link>

          <span className="mx-1 hidden h-5 w-px bg-white/15 sm:inline-block" />

          <LanguageSwitcher />

          {loading ? null : user ? (
            <>
              <Link
                href={`/${locale}/dashboard`}
                className="rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white"
              >
                {t("nav.dashboard")}
              </Link>
              <Link
                href={`/${locale}/support`}
                className="hidden rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white sm:inline-block"
              >
                {t("nav.support")}
              </Link>
              <Link
                href={`/${locale}/settings`}
                className="hidden rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white sm:inline-block"
              >
                {t("nav.settings")}
              </Link>
              <span className="px-2">
                <NotificationBell />
              </span>
              <button
                type="button"
                onClick={logout}
                className="rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white"
              >
                {t("nav.logout")}
              </button>
            </>
          ) : (
            <>
              <Link
                href={`/${locale}/login`}
                className="rounded-full px-3 py-1.5 font-medium text-white/70 transition hover:text-white"
              >
                {t("nav.login")}
              </Link>
              <Link
                href={`/${locale}/register`}
                className="inline-flex items-center justify-center rounded-full border border-white/20 px-4 py-1.5 font-semibold text-white transition hover:border-white/40 hover:bg-white/5"
              >
                {t("nav.register")}
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
