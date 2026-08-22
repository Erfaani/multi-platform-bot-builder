/** Linking a Telegram/Bale account to this website account (spec §47) — what unlocks
 * the owner admin menu inside the bot. Per-user, not per-tenant: link once and it
 * works for every bot the account can already manage from the dashboard. */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";

export type ChannelPlatform = "telegram" | "bale";

export interface ChannelIdentityView {
  id: number;
  platform: ChannelPlatform;
  username: string;
  linked_at: string;
}

export interface ChannelLinkCodeView {
  code: string;
  platform: ChannelPlatform;
  expires_at: string;
}

export const channelLinksApi = {
  list: (locale: Locale) => apiFetch<ChannelIdentityView[]>("/channel-links/", { locale }),

  createCode: (platform: ChannelPlatform, locale: Locale) =>
    apiFetch<ChannelLinkCodeView>("/channel-links/", {
      method: "POST",
      body: { platform },
      locale,
    }),

  unlink: (id: number, locale: Locale) =>
    apiFetch<void>(`/channel-links/${id}/`, { method: "DELETE", locale }),
};
