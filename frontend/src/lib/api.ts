/**
 * API client.
 *
 * Two rules it exists to enforce:
 *  - every request carries the active workspace (`X-Tenant`) and the locale;
 *  - every failure surfaces the backend's `{ error: { code, message } }` envelope,
 *    so the UI shows the server's localized message rather than inventing one.
 */

import type { Locale } from "@/i18n/config";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

//: The backend's origin, without the `/api/v1` suffix — media URLs (product/property/
//: course photos) come back from the API as paths relative to the backend
//: (`/media/public/...`), not the frontend, which is a different origin in dev.
const API_ORIGIN = API_BASE.replace(/\/api\/v1\/?$/, "");

/** Resolve a `/media/public/...`-shaped path from the API into a URL the browser can
 * actually load. A falsy `path` (no photo yet) passes through unchanged. */
export function mediaUrl(path: string): string {
  if (!path) return path;
  return `${API_ORIGIN}${path}`;
}

const ACCESS_KEY = "bb.access";
const REFRESH_KEY = "bb.refresh";
const TENANT_KEY = "bb.tenant";

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  field_errors?: Record<string, string[]>;
  trace_id?: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiErrorBody,
  ) {
    super(body.message);
    this.name = "ApiError";
  }

  get fieldErrors(): Record<string, string[]> {
    return this.body.field_errors ?? {};
  }
}

export const tokenStore = {
  get access() {
    return typeof window === "undefined" ? null : localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return typeof window === "undefined" ? null : localStorage.getItem(REFRESH_KEY);
  },
  get tenant() {
    return typeof window === "undefined" ? null : localStorage.getItem(TENANT_KEY);
  },
  setTokens(access: string, refresh?: string) {
    localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  },
  setTenant(publicId: string | null) {
    if (publicId) localStorage.setItem(TENANT_KEY, publicId);
    else localStorage.removeItem(TENANT_KEY);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(TENANT_KEY);
  },
};

interface RequestOptions {
  method?: string;
  body?: unknown;
  locale?: Locale;
  auth?: boolean;
  tenant?: string | null;
  /** Bearer secret for an anonymous builder quote (X-Quote-Session). */
  quoteSession?: string | null;
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokenStore.refresh;
  if (!refresh) return false;

  const response = await fetch(`${API_BASE}/auth/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) {
    tokenStore.clear();
    return false;
  }
  const data = await response.json();
  tokenStore.setTokens(data.access, data.refresh);
  return true;
}

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
  retrying = false,
): Promise<T> {
  const { method = "GET", body, locale, auth = true, tenant, quoteSession } = options;

  // A FormData body (file uploads) must NOT get a JSON Content-Type or a stringified
  // body — the browser sets its own multipart boundary header, which fetch can only do
  // correctly if this code never touches Content-Type itself.
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;

  const headers: Record<string, string> = isFormData ? {} : { "Content-Type": "application/json" };
  if (locale) headers["Accept-Language"] = locale;
  if (quoteSession) headers["X-Quote-Session"] = quoteSession;

  if (auth && tokenStore.access) {
    headers["Authorization"] = `Bearer ${tokenStore.access}`;
  }
  const activeTenant = tenant === undefined ? tokenStore.tenant : tenant;
  if (activeTenant) headers["X-Tenant"] = activeTenant;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isFormData ? (body as FormData) : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, { code: "error.network", message: "Could not reach the server." });
  }

  // One transparent retry after refreshing an expired access token.
  if (response.status === 401 && auth && !retrying && (await refreshAccessToken())) {
    return apiFetch<T>(path, options, true);
  }

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const error: ApiErrorBody = payload?.error ?? {
      code: "error.unexpected",
      message: "Something went wrong.",
    };
    throw new ApiError(response.status, error);
  }

  return payload as T;
}

// --- typed endpoints ---------------------------------------------------------

export interface User {
  id: string;
  email: string;
  full_name: string;
  preferred_locale: string;
  preferred_currency: string;
  is_email_verified: boolean;
  staff_scopes: string[];
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  default_locale: string;
  default_currency: string;
  my_role?: string;
}

export const api = {
  login: (email: string, password: string, locale?: Locale) =>
    apiFetch<{ access: string; refresh: string; user: User }>("/auth/login/", {
      method: "POST",
      body: { email, password },
      auth: false,
      locale,
    }),

  register: (payload: Record<string, unknown>, locale?: Locale) =>
    apiFetch<{ access: string; refresh: string; user: User }>("/auth/register/", {
      method: "POST",
      body: payload,
      auth: false,
      locale,
    }),

  me: (locale?: Locale) => apiFetch<User>("/auth/me/", { locale }),

  updateMe: (payload: Record<string, unknown>, locale?: Locale) =>
    apiFetch<User>("/auth/me/", { method: "PATCH", body: payload, locale }),

  tenants: (locale?: Locale) => apiFetch<Tenant[]>("/tenants/", { locale }),

  createTenant: (name: string, locale?: Locale) =>
    apiFetch<Tenant>("/tenants/", { method: "POST", body: { name }, locale }),

  activeTenant: (locale?: Locale) =>
    apiFetch<Tenant & { role: string; scopes: string[] }>("/tenants/active/", { locale }),

  currencies: (locale?: Locale) =>
    apiFetch<
      { code: string; name: string; symbol: string; exponent: number; display_unit: string; display_divisor: number }[]
    >("/currencies/", { auth: false, locale }),

  publicSettings: (locale?: Locale) =>
    apiFetch<Record<string, unknown>>("/settings/public/", { auth: false, locale }),
};
