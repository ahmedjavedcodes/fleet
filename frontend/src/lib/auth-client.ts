"use client";

// Client-only auth helpers — for Client Components (login form, copilot chat,
// logout button). See auth-shared.ts for why this is a plain cookie and not
// httpOnly.
import { AUTH_COOKIE_NAME } from "@/lib/auth-shared";

const MAX_AGE_SECONDS = 60 * 60 * 12; // 12h ceiling; actual JWT expiry (from TokenResponse.expires_in) governs real validity.

export function getClientToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${AUTH_COOKIE_NAME}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function setClientToken(token: string, expiresInSeconds: number): void {
  const maxAge = Math.min(expiresInSeconds, MAX_AGE_SECONDS);
  document.cookie = `${AUTH_COOKIE_NAME}=${encodeURIComponent(token)}; path=/; max-age=${maxAge}; samesite=lax`;
}

export function clearClientToken(): void {
  document.cookie = `${AUTH_COOKIE_NAME}=; path=/; max-age=0; samesite=lax`;
}
