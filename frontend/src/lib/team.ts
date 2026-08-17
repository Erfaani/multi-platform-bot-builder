/** Team members and invitations for the active workspace (spec §26). */

import type { Locale } from "@/i18n/config";
import { apiFetch } from "./api";

export type TenantRole = "OWNER" | "MANAGER" | "STAFF";

export interface MembershipView {
  id: number;
  user_id: string;
  email: string;
  full_name: string;
  role: TenantRole;
  scopes: string[];
  accepted_at: string | null;
  created_at: string;
}

export interface InvitationView {
  id: number;
  email: string;
  role: TenantRole;
  invited_by_email: string | null;
  expires_at: string;
  created_at: string;
}

export interface AddMemberResult {
  outcome: "added" | "invited";
  membership?: MembershipView;
  invitation_email?: string;
}

export interface InvitationPreview {
  tenant_name: string;
  role: TenantRole;
  email: string;
}

export const teamApi = {
  members: (tenantId: string, locale: Locale) =>
    apiFetch<MembershipView[]>(`/tenants/${tenantId}/members/`, { locale }),

  addMember: (tenantId: string, email: string, role: TenantRole, locale: Locale) =>
    apiFetch<AddMemberResult>(`/tenants/${tenantId}/members/`, {
      method: "POST",
      body: { email, role },
      locale,
    }),

  removeMember: (tenantId: string, membershipId: number, locale: Locale) =>
    apiFetch<void>(`/tenants/${tenantId}/members/${membershipId}/`, {
      method: "DELETE",
      locale,
    }),

  invitations: (tenantId: string, locale: Locale) =>
    apiFetch<InvitationView[]>(`/tenants/${tenantId}/invitations/`, { locale }),

  revokeInvitation: (tenantId: string, invitationId: number, locale: Locale) =>
    apiFetch<void>(`/tenants/${tenantId}/invitations/${invitationId}/`, {
      method: "DELETE",
      locale,
    }),

  previewInvitation: (token: string, locale: Locale) =>
    apiFetch<InvitationPreview>("/invitations/preview/", {
      method: "POST",
      body: { token },
      auth: false,
      locale,
    }),

  acceptInvitation: (token: string, locale: Locale) =>
    apiFetch<MembershipView>("/invitations/accept/", {
      method: "POST",
      body: { token },
      locale,
    }),
};
