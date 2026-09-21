// Server-only auth helpers — for Server Components and route handlers.
// Never import this file from a "use client" component (next/headers throws
// there); use auth-client.ts instead.
import "server-only";
import { cookies } from "next/headers";

import { apiFetch } from "@/lib/api-client";
import { AUTH_COOKIE_NAME } from "@/lib/auth-shared";
import type { MeResponse } from "@/lib/types/auth";

export async function getServerToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(AUTH_COOKIE_NAME)?.value ?? null;
}

/** Resolves the current session for a Server Component. Returns null when
 * there's no token or it's expired/invalid — callers decide whether that
 * means "redirect to /login" or "render an empty state". */
export async function getServerSession(): Promise<MeResponse | null> {
  const token = await getServerToken();
  if (!token) return null;

  try {
    return await apiFetch<MeResponse>("/api/v1/auth/me", { token });
  } catch {
    return null;
  }
}
