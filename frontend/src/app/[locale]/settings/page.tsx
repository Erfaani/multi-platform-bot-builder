"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { teamApi, type InvitationView, type MembershipView, type TenantRole } from "@/lib/team";

export default function SettingsPage() {
  const t = useTranslations();
  const { locale } = useIntl();
  const router = useRouter();
  const { user, tenants, activeTenantId, loading } = useAuth();

  const [members, setMembers] = useState<MembershipView[]>([]);
  const [invitations, setInvitations] = useState<InvitationView[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TenantRole>("STAFF");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const active = tenants.find((tenant) => tenant.id === activeTenantId);
  const canManage = active?.my_role === "OWNER" || active?.my_role === "MANAGER";

  const load = useCallback(() => {
    if (!activeTenantId) return;
    teamApi
      .members(activeTenantId, locale)
      .then(setMembers)
      .catch(() => setError(t("error.network")));
    teamApi
      .invitations(activeTenantId, locale)
      .then(setInvitations)
      .catch(() => {});
  }, [activeTenantId, locale, t]);

  useEffect(() => {
    if (!loading && !user) router.replace(`/${locale}/login`);
  }, [loading, user, router, locale]);

  useEffect(() => {
    if (user && activeTenantId) load();
  }, [user, activeTenantId, load]);

  async function invite(event: React.FormEvent) {
    event.preventDefault();
    if (!activeTenantId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await teamApi.addMember(activeTenantId, email, role, locale);
      setEmail("");
      if (result.outcome === "added") {
        setNotice(t("settings.team.added"));
      } else {
        setNotice(t("settings.team.invited"));
      }
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(membershipId: number) {
    if (!activeTenantId) return;
    try {
      await teamApi.removeMember(activeTenantId, membershipId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function revoke(invitationId: number) {
    if (!activeTenantId) return;
    try {
      await teamApi.revokeInvitation(activeTenantId, invitationId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  if (loading) return <p className="text-muted">{t("common.loading")}</p>;
  if (!user) return null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("settings.title")}</h1>

      {!active ? (
        <p className="text-sm text-muted">{t("dashboard.noWorkspace")}</p>
      ) : (
        <>
          <section className="card space-y-2">
            <h2 className="font-medium">{t("settings.workspace")}</h2>
            <p className="text-sm text-muted">
              {active.name} · {active.default_currency} · {t("dashboard.role")}: {active.my_role}
            </p>
          </section>

          <section className="card space-y-3">
            <h2 className="font-medium">{t("settings.team.title")}</h2>

            <ul className="space-y-2">
              {members.map((member) => (
                <li
                  key={member.id}
                  className="flex items-center justify-between gap-3 border-b border-line pb-2 text-sm last:border-0"
                >
                  <span>
                    <span className="block">{member.full_name || member.email}</span>
                    <span className="block text-xs text-muted">
                      {member.email} · {member.role}
                    </span>
                  </span>
                  {canManage && member.role !== "OWNER" ? (
                    <button
                      type="button"
                      onClick={() => remove(member.id)}
                      className="text-xs text-red-500"
                    >
                      {t("settings.team.remove")}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>

            {invitations.length > 0 ? (
              <div className="space-y-2 border-t border-line pt-3">
                <p className="text-xs uppercase tracking-wide text-muted">
                  {t("settings.team.pending")}
                </p>
                {invitations.map((invitation) => (
                  <div
                    key={invitation.id}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span>
                      {invitation.email} · {invitation.role}
                    </span>
                    {canManage ? (
                      <button
                        type="button"
                        onClick={() => revoke(invitation.id)}
                        className="text-xs text-red-500"
                      >
                        {t("settings.team.revoke")}
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}

            {canManage ? (
              <form onSubmit={invite} className="flex flex-wrap gap-2 border-t border-line pt-3">
                <input
                  type="email"
                  className="field flex-1"
                  placeholder={t("settings.team.emailPlaceholder")}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
                <select
                  className="field w-auto"
                  value={role}
                  onChange={(event) => setRole(event.target.value as TenantRole)}
                >
                  <option value="STAFF">{t("settings.team.role.STAFF")}</option>
                  <option value="MANAGER">{t("settings.team.role.MANAGER")}</option>
                </select>
                <button type="submit" disabled={busy} className="btn-primary shrink-0">
                  {t("settings.team.invite")}
                </button>
              </form>
            ) : null}

            {notice ? <p className="text-sm text-green-600">{notice}</p> : null}
            {error ? (
              <p role="alert" className="text-sm text-red-500">
                {error}
              </p>
            ) : null}
          </section>
        </>
      )}
    </div>
  );
}
