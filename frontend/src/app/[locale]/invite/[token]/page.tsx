"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { teamApi, type InvitationPreview } from "@/lib/team";

export default function InviteAcceptPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const { user, loading, login, register, reload, logout } = useAuth();

  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(false);

  const token = params?.token ?? "";

  useEffect(() => {
    if (!token) return;
    teamApi
      .previewInvitation(token, locale)
      .then(setPreview)
      .catch((err) =>
        setPreviewError(err instanceof ApiError ? err.message : t("error.network")),
      );
  }, [token, locale, t]);

  const accept = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await teamApi.acceptInvitation(token, locale);
      // The newly joined workspace is now among `tenants`; `reload()` re-picks the
      // active one from that list. Which one it lands on if the user already
      // belonged to several is a `dashboard` workspace-switch away, not a blocker.
      await reload();
      setAccepted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }, [token, locale, reload, t]);

  const emailMatches =
    !!user && !!preview && user.email.toLowerCase() === preview.email.toLowerCase();

  // Auto-accept the moment a matching session appears, whether the user was already
  // logged in or just finished logging in / registering on this page.
  useEffect(() => {
    if (emailMatches && !accepted && !busy) void accept();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emailMatches]);

  useEffect(() => {
    if (accepted) {
      const timer = setTimeout(() => router.push(`/${locale}/dashboard`), 1500);
      return () => clearTimeout(timer);
    }
  }, [accepted, router, locale]);

  async function onLogin(event: React.FormEvent) {
    event.preventDefault();
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      await login(preview.email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
      setBusy(false);
    }
  }

  async function onRegister(event: React.FormEvent) {
    event.preventDefault();
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      await register({
        email: preview.email,
        password,
        first_name: firstName,
        last_name: lastName,
        preferred_locale: locale,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
      setBusy(false);
    }
  }

  if (previewError) {
    return <p className="text-sm text-red-500">{previewError}</p>;
  }
  if (!preview) {
    return <p className="text-muted">{t("common.loading")}</p>;
  }

  return (
    <div className="mx-auto max-w-sm space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("invite.title")}</h1>
        <p className="text-sm text-muted">
          {t("invite.summary", { tenant: preview.tenant_name, email: preview.email })}
        </p>
      </div>

      {accepted ? (
        <p className="text-sm text-green-600">{t("invite.accepted")}</p>
      ) : loading ? (
        <p className="text-muted">{t("common.loading")}</p>
      ) : user && !emailMatches ? (
        <div className="card space-y-2">
          <p className="text-sm text-muted">
            {t("invite.wrongAccount", { email: preview.email })}
          </p>
          <button type="button" onClick={logout} className="btn-ghost">
            {t("nav.logout")}
          </button>
        </div>
      ) : user && emailMatches ? (
        <button type="button" onClick={accept} disabled={busy} className="btn-primary w-full">
          {busy ? t("common.loading") : t("invite.accept")}
        </button>
      ) : (
        <div className="card space-y-4">
          <div className="flex gap-4 border-b border-line text-sm">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={mode === "login" ? "border-b-2 border-accent pb-2" : "pb-2 text-muted"}
            >
              {t("nav.login")}
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={mode === "register" ? "border-b-2 border-accent pb-2" : "pb-2 text-muted"}
            >
              {t("nav.register")}
            </button>
          </div>

          {mode === "login" ? (
            <form onSubmit={onLogin} className="space-y-3">
              <p className="text-sm text-muted" dir="ltr">
                {preview.email}
              </p>
              <label className="block space-y-1">
                <span className="text-sm text-muted">{t("auth.field.password")}</span>
                <input
                  type="password"
                  required
                  autoComplete="current-password"
                  className="field"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
              <button type="submit" disabled={busy} className="btn-primary w-full">
                {busy ? t("common.loading") : t("auth.login.submit")}
              </button>
            </form>
          ) : (
            <form onSubmit={onRegister} className="space-y-3">
              <p className="text-sm text-muted" dir="ltr">
                {preview.email}
              </p>
              <div className="grid grid-cols-2 gap-3">
                <label className="block space-y-1">
                  <span className="text-sm text-muted">{t("auth.field.firstName")}</span>
                  <input
                    className="field"
                    value={firstName}
                    onChange={(event) => setFirstName(event.target.value)}
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-sm text-muted">{t("auth.field.lastName")}</span>
                  <input
                    className="field"
                    value={lastName}
                    onChange={(event) => setLastName(event.target.value)}
                  />
                </label>
              </div>
              <label className="block space-y-1">
                <span className="text-sm text-muted">{t("auth.field.password")}</span>
                <input
                  type="password"
                  required
                  minLength={12}
                  autoComplete="new-password"
                  className="field"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
                <span className="block text-xs text-muted">{t("auth.password.hint")}</span>
              </label>
              <button type="submit" disabled={busy} className="btn-primary w-full">
                {busy ? t("common.loading") : t("auth.register.submit")}
              </button>
            </form>
          )}
        </div>
      )}

      {error ? (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      ) : null}
    </div>
  );
}
