"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { apiClient, ApiError } from "./api";
import { canAccess, type AccessRequirement } from "./auth-policy";
import type { StaffSession } from "./contracts";
import type { DemoPersona } from "./demo-personas";

type AuthState = {
  session: StaffSession | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<StaffSession | null>;
  login: (email: string, password: string) => Promise<StaffSession>;
  demoLogin: (persona: DemoPersona) => Promise<StaffSession>;
  logout: () => Promise<void>;
  selectLocation: (locationId: string) => Promise<void>;
};

const StaffAuthContext = createContext<AuthState | null>(null);

export function StaffAuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [session, setSession] = useState<StaffSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const current = await apiClient.get<StaffSession>("/staff/auth/session");
      setSession(current);
      setError(null);
      return current;
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        setSession(null);
        setError(null);
        return null;
      }
      setError(reason instanceof Error ? reason.message : "The staff session could not be checked.");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const isPublicRoute = pathname === "/" || ["/restaurants", "/r", "/reserve", "/dine", "/order", "/join", "/login", "/offline"].some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
    if (isPublicRoute) { setSession(null); setError(null); setLoading(false); return; }
    void refresh();
  }, [pathname, refresh]);

  const value = useMemo<AuthState>(() => ({
    session,
    loading,
    error,
    refresh,
    async login(email, password) {
      const current = await apiClient.post<StaffSession>("/staff/auth/login", { email, password });
      setSession(current);
      setError(null);
      return current;
    },
    async demoLogin(persona) {
      const current = await apiClient.post<StaffSession>(
        "/staff/auth/demo-session",
        { persona },
      );

      setSession(current);
      setError(null);

      return current;
    },
    async logout() {
      await apiClient.post<void>("/staff/auth/logout");
      setSession(null);
    },
    async selectLocation(locationId) {
      const current = await apiClient.post<StaffSession>("/staff/auth/active-location", { location_id: locationId });
      setSession(current);
    },
  }), [error, loading, refresh, session]);

  return <StaffAuthContext.Provider value={value}>{children}</StaffAuthContext.Provider>;
}

export function useStaffAuth() {
  const context = useContext(StaffAuthContext);
  if (!context) throw new Error("useStaffAuth must be used inside StaffAuthProvider");
  return context;
}

export function RequireStaffAccess({
  children,
  fallback,
  ...requirement
}: AccessRequirement & { children: React.ReactNode; fallback?: React.ReactNode }) {
  const { session, loading, error } = useStaffAuth();
  if (loading) return <p className="loading" role="status">Checking staff access…</p>;
  if (error) return <div className="notice notice-danger" role="alert">{error}</div>;
  if (!canAccess(session, requirement)) {
    return fallback ?? <div className="notice notice-warning" role="alert">You do not have access to this workspace.</div>;
  }
  return children;
}
