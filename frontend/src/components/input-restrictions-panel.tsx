"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { botsApi, type InputRestrictionsView } from "@/lib/bots";

function parseList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function InputRestrictionsPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [policy, setPolicy] = useState<InputRestrictionsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const [allowedCallingCodes, setAllowedCallingCodes] = useState("");
  const [blockedPhoneNumbers, setBlockedPhoneNumbers] = useState("");
  const [collectEmail, setCollectEmail] = useState(false);
  const [allowedEmailDomains, setAllowedEmailDomains] = useState("");
  const [blockedEmailDomains, setBlockedEmailDomains] = useState("");
  const [strictEmailFormat, setStrictEmailFormat] = useState(true);

  useEffect(() => {
    botsApi
      .inputRestrictions(botId, locale)
      .then((body) => {
        setPolicy(body);
        setAllowedCallingCodes(body.allowed_calling_codes.join(", "));
        setBlockedPhoneNumbers(body.blocked_phone_numbers.join(", "));
        setCollectEmail(body.collect_email_on_consultation);
        setAllowedEmailDomains(body.allowed_email_domains.join(", "));
        setBlockedEmailDomains(body.blocked_email_domains.join(", "));
        setStrictEmailFormat(body.strict_email_format);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : t("error.network")));
  }, [botId, locale, t]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await botsApi.updateInputRestrictions(
        botId,
        {
          allowed_calling_codes: parseList(allowedCallingCodes),
          blocked_phone_numbers: parseList(blockedPhoneNumbers),
          collect_email_on_consultation: collectEmail,
          allowed_email_domains: parseList(allowedEmailDomains),
          blocked_email_domains: parseList(blockedEmailDomains),
          strict_email_format: strictEmailFormat,
        },
        locale,
      );
      setPolicy(updated);
      setAllowedCallingCodes(updated.allowed_calling_codes.join(", "));
      setBlockedPhoneNumbers(updated.blocked_phone_numbers.join(", "));
      setAllowedEmailDomains(updated.allowed_email_domains.join(", "));
      setBlockedEmailDomains(updated.blocked_email_domains.join(", "));
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  if (!policy) {
    return error ? <p className="text-sm text-red-500">{error}</p> : null;
  }

  return (
    <section className="card space-y-3">
      <h2 className="font-medium">{t("bot.inputRestrictions.title")}</h2>
      <p className="text-sm text-muted">{t("bot.inputRestrictions.hint")}</p>

      <form onSubmit={save} className="space-y-4">
        <div className="space-y-2 border-t border-line pt-3">
          <h3 className="text-sm font-medium text-muted">{t("bot.inputRestrictions.phoneSection")}</h3>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.inputRestrictions.allowedCallingCodes")}</span>
            <input
              className="field"
              dir="ltr"
              placeholder="+98, +1"
              value={allowedCallingCodes}
              onChange={(e) => setAllowedCallingCodes(e.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("bot.inputRestrictions.blockedPhoneNumbers")}</span>
            <input
              className="field"
              dir="ltr"
              placeholder="+1 555 010 0100"
              value={blockedPhoneNumbers}
              onChange={(e) => setBlockedPhoneNumbers(e.target.value)}
            />
          </label>
        </div>

        <div className="space-y-2 border-t border-line pt-3">
          <h3 className="text-sm font-medium text-muted">{t("bot.inputRestrictions.emailSection")}</h3>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={collectEmail}
              onChange={(e) => setCollectEmail(e.target.checked)}
            />
            {t("bot.inputRestrictions.collectEmail")}
          </label>
          {collectEmail ? (
            <>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={strictEmailFormat}
                  onChange={(e) => setStrictEmailFormat(e.target.checked)}
                />
                {t("bot.inputRestrictions.strictFormat")}
              </label>
              <label className="block space-y-1">
                <span className="text-sm text-muted">{t("bot.inputRestrictions.allowedEmailDomains")}</span>
                <input
                  className="field"
                  dir="ltr"
                  placeholder="company.com"
                  value={allowedEmailDomains}
                  onChange={(e) => setAllowedEmailDomains(e.target.value)}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-sm text-muted">{t("bot.inputRestrictions.blockedEmailDomains")}</span>
                <input
                  className="field"
                  dir="ltr"
                  placeholder="spam.example"
                  value={blockedEmailDomains}
                  onChange={(e) => setBlockedEmailDomains(e.target.value)}
                />
              </label>
            </>
          ) : null}
        </div>

        {error ? (
          <p role="alert" className="text-sm text-red-500">
            {error}
          </p>
        ) : null}
        {saved && !busy ? <p className="text-sm text-green-600">{t("common.saved")}</p> : null}

        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? t("common.loading") : t("common.save")}
        </button>
      </form>
    </section>
  );
}
