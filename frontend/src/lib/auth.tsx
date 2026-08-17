"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError, tokenStore, type Tenant, type User } from "./api";

interface AuthValue {
  user: User | null;
  tenants: Tenant[];
  activeTenantId: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: Record<string, unknown>) => Promise<void>;
  logout: () => void;
  selectTenant: (id: string | null) => void;
  reload: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [activeTenantId, setActiveTenantId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadSession = useCallback(async () => {
    if (!tokenStore.access) {
      setUser(null);
      setTenants([]);
      setLoading(false);
      return;
    }
    try {
      const [me, list] = await Promise.all([api.me(), api.tenants()]);
      setUser(me);
      setTenants(list);

      // Keep the stored workspace only if it is still one the user belongs to;
      // a stale id would otherwise produce 404s on every request.
      const stored = tokenStore.tenant;
      const valid = stored && list.some((t) => t.id === stored) ? stored : list[0]?.id ?? null;
      tokenStore.setTenant(valid);
      setActiveTenantId(valid);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        tokenStore.clear();
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api.login(email, password);
      tokenStore.setTokens(result.access, result.refresh);
      await loadSession();
    },
    [loadSession],
  );

  const register = useCallback(
    async (payload: Record<string, unknown>) => {
      const result = await api.register(payload);
      tokenStore.setTokens(result.access, result.refresh);
      await loadSession();
    },
    [loadSession],
  );

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    setTenants([]);
    setActiveTenantId(null);
  }, []);

  const selectTenant = useCallback((id: string | null) => {
    tokenStore.setTenant(id);
    setActiveTenantId(id);
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      tenants,
      activeTenantId,
      loading,
      login,
      register,
      logout,
      selectTenant,
      reload: loadSession,
    }),
    [user, tenants, activeTenantId, loading, login, register, logout, selectTenant, loadSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider.");
  return context;
}
