"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const { register } = useAuth();

  const [form, setForm] = useState({
    email: "",
    password: "",
    first_name: "",
    last_name: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [key]: event.target.value }));
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      await register({ ...form, preferred_locale: locale });
      router.push(`/${locale}/dashboard`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        setFieldErrors(err.fieldErrors);
      } else {
        setError(t("error.generic"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm space-y-6">
      <h1 className="text-2xl font-semibold">{t("auth.register.title")}</h1>

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("auth.field.firstName")}</span>
            <input className="field" value={form.first_name} onChange={update("first_name")} />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-muted">{t("auth.field.lastName")}</span>
            <input className="field" value={form.last_name} onChange={update("last_name")} />
          </label>
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("auth.field.email")}</span>
          <input
            type="email"
            required
            autoComplete="email"
            className="field"
            value={form.email}
            onChange={update("email")}
          />
          {fieldErrors.email?.map((message) => (
            <span key={message} className="block text-xs text-red-500">
              {message}
            </span>
          ))}
        </label>

        <label className="block space-y-1">
          <span className="text-sm text-muted">{t("auth.field.password")}</span>
          <input
            type="password"
            required
            minLength={12}
            autoComplete="new-password"
            className="field"
            value={form.password}
            onChange={update("password")}
          />
          <span className="block text-xs text-muted">{t("auth.password.hint")}</span>
          {fieldErrors.password?.map((message) => (
            <span key={message} className="block text-xs text-red-500">
              {message}
            </span>
          ))}
        </label>

        {error ? (
          <p role="alert" className="text-sm text-red-500">
            {error}
          </p>
        ) : null}

        <button type="submit" disabled={busy} className="btn-primary w-full">
          {busy ? t("common.loading") : t("auth.register.submit")}
        </button>
      </form>

      <p className="text-sm text-muted">
        {t("auth.haveAccount")}{" "}
        <Link href={`/${locale}/login`} className="text-accent">
          {t("nav.login")}
        </Link>
      </p>
    </div>
  );
}
