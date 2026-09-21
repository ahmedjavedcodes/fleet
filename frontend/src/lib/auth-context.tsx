"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/lib/api-client";
import { clearClientToken, setClientToken } from "@/lib/auth-client";
import type { LoginRequest, MeResponse, TokenResponse } from "@/lib/types/auth";

interface AuthContextValue {
  session: MeResponse | null;
  login: (credentials: LoginRequest) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** `initialSession` is resolved server-side (see auth-server.ts) and passed
 * down from the root layout, so the app doesn't re-fetch /auth/me on every
 * client mount. */
export function AuthProvider({
  initialSession,
  children,
}: {
  initialSession: MeResponse | null;
  children: React.ReactNode;
}) {
  const [session, setSession] = useState<MeResponse | null>(initialSession);
  const router = useRouter();

  const login = useCallback(
    async (credentials: LoginRequest) => {
      const token = await apiFetch<TokenResponse>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify(credentials),
      });
      setClientToken(token.access_token, token.expires_in);
      const me = await apiFetch<MeResponse>("/api/v1/auth/me", { token: token.access_token });
      setSession(me);
      router.push("/dashboard");
      router.refresh();
    },
    [router],
  );

  const logout = useCallback(() => {
    clearClientToken();
    setSession(null);
    router.push("/login");
    router.refresh();
  }, [router]);

  const value = useMemo(() => ({ session, login, logout }), [session, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
