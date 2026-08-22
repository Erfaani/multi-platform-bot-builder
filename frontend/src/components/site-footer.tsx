"use client";

import Link from "next/link";
import { Bot } from "lucide-react";
import { useIntl, useTranslations } from "@/i18n/provider";

export function SiteFooter() {
  const t = useTranslations();
  const { locale } = useIntl();
  const year = new Date().getFullYear();

  const productLinks = [
    { href: "templates", label: t("nav.templates") },
    { href: "features", label: t("nav.features") },
    { href: "pricing", label: t("nav.pricing") },
    { href: "how-it-works", label: t("nav.howItWorks") },
    { href: "build", label: t("nav.build") },
  ];

  const accountLinks = [
    { href: "dashboard", label: t("nav.dashboard") },
    { href: "support", label: t("nav.support") },
    { href: "settings", label: t("nav.settings") },
  ];

  return (
    <footer className="bg-dark text-white/70">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 sm:grid-cols-[1.4fr_1fr_1fr]">
          <div className="space-y-3">
            <Link href={`/${locale}`} className="flex items-center gap-2.5">
              <span className="icon-badge bg-accent">
                <Bot className="h-5 w-5 text-white" strokeWidth={2.25} />
              </span>
              <span className="text-lg font-bold tracking-tight text-white">{t("brand.name")}</span>
            </Link>
            <p className="max-w-xs text-sm leading-relaxed text-white/60">{t("brand.tagline")}</p>
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-white">{t("footer.product")}</h3>
            <ul className="space-y-2 text-sm">
              {productLinks.map((link) => (
                <li key={link.href}>
                  <Link href={`/${locale}/${link.href}`} className="transition hover:text-white">
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-white">{t("footer.account")}</h3>
            <ul className="space-y-2 text-sm">
              {accountLinks.map((link) => (
                <li key={link.href}>
                  <Link href={`/${locale}/${link.href}`} className="transition hover:text-white">
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-10 flex flex-col-reverse items-center justify-between gap-3 border-t border-white/10 pt-6 text-xs text-white/50 sm:flex-row">
          <p>
            © {year} {t("brand.name")}. {t("footer.rights")}
          </p>
        </div>
      </div>
    </footer>
  );
}
