"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { useAuth } from "@/lib/auth";
import { botsApi, type BotView } from "@/lib/bots";

export default function BotsPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const { user, loading, activeTenantId } = useAuth();

  const [bots, setBots] = useState<BotView[]>([]);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    botsApi
      .list(locale)
      .then((page) => setBots(page.results))
      .catch(() => setFailed(true));
  }, [locale]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user) load();
  }, [user, activeTenantId, load]);

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("bots.title")}</h1>

      {failed ? <p className="text-sm text-red-500">{t("error.network")}</p> : null}

      {bots.length === 0 ? (
        <div className="card space-y-3">
          <p className="text-sm text-muted">{t("bots.empty")}</p>
          <Link href={`/${locale}/build`} className="btn-primary inline-flex">
            {t("home.cta.primary")}
          </Link>
        </div>
      ) : (
        <ul className="space-y-3">
          {bots.map((bot) => {
            const needsToken = bot.instances.some((i) => i.needs_token);
            return (
              <li key={bot.id}>
                <Link
                  href={`/${locale}/bots/${bot.id}`}
                  className="card block space-y-1 transition hover:border-accent"
                >
                  <span className="flex items-center justify-between gap-3">
                    <span className="font-medium">{bot.name}</span>
                    <span
                      className={`rounded-md border px-2 py-0.5 text-xs ${
                        bot.status === "ACTIVE"
                          ? "border-green-600/40 text-green-600"
                          : bot.status === "FAILED"
                            ? "border-red-500/40 text-red-500"
                            : "border-accent/40 text-accent"
                      }`}
                    >
                      {t(`bot.status.${bot.status}`)}
                    </span>
                  </span>

                  <span className="block text-xs text-muted">
                    {bot.instances
                      .map((i) => (i.username ? `@${i.username}` : i.platform))
                      .join(" · ")}
                  </span>

                  {needsToken ? (
                    <span className="block text-xs text-amber-600">
                      {t("bots.needsToken")}
                    </span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
