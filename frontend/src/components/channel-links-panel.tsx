"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import {
  channelLinksApi,
  type ChannelIdentityView,
  type ChannelLinkCodeView,
  type ChannelPlatform,
} from "@/lib/channel-links";

const PLATFORMS: ChannelPlatform[] = ["telegram", "bale"];

export function ChannelLinksPanel() {
  const t = useTranslations();
  const { locale } = useIntl();

  const [identities, setIdentities] = useState<ChannelIdentityView[]>([]);
  const [pendingCode, setPendingCode] = useState<ChannelLinkCodeView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<ChannelPlatform | null>(null);

  function load() {
    channelLinksApi.list(locale).then(setIdentities).catch(() => setError(t("error.network")));
  }

  useEffect(load, [locale, t]);

  async function generateCode(platform: ChannelPlatform) {
    setBusy(platform);
    setError(null);
    try {
      setPendingCode(await channelLinksApi.createCode(platform, locale));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(null);
    }
  }

  async function unlink(id: number) {
    try {
      await channelLinksApi.unlink(id, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{t("settings.channelLinks.title")}</h2>
      <p className="text-sm text-muted">{t("settings.channelLinks.hint")}</p>

      {identities.length > 0 ? (
        <ul className="space-y-1">
          {identities.map((identity) => (
            <li key={identity.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="capitalize">
                {identity.platform}
                {identity.username ? ` · @${identity.username}` : ""}
              </span>
              <button type="button" onClick={() => unlink(identity.id)} className="text-xs text-red-500">
                {t("settings.channelLinks.unlink")}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">{t("settings.channelLinks.empty")}</p>
      )}

      <div className="flex flex-wrap gap-2 border-t border-line pt-3">
        {PLATFORMS.map((platform) => (
          <button
            key={platform}
            type="button"
            disabled={busy === platform}
            onClick={() => generateCode(platform)}
            className="btn-ghost capitalize"
          >
            {t("settings.channelLinks.linkButton", { platform })}
          </button>
        ))}
      </div>

      {pendingCode ? (
        <div className="rounded-lg border border-accent p-3 text-sm">
          <p>{t("settings.channelLinks.instructions", { platform: pendingCode.platform })}</p>
          <p className="mt-2 font-mono text-lg" dir="ltr">
            /link {pendingCode.code}
          </p>
          <p className="mt-1 text-xs text-muted">
            {t("settings.channelLinks.expires", {
              time: new Date(pendingCode.expires_at).toLocaleTimeString(
                locale === "fa" ? "fa-IR" : "en-US",
              ),
            })}
          </p>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      ) : null}
    </section>
  );
}
