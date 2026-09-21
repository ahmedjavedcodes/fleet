// Shared constant for both auth-server.ts and auth-client.ts. The backend
// (auth.py) returns the JWT in a JSON body, not a Set-Cookie header, so the
// frontend mirrors it into a cookie itself after login so Server Components
// can read it via next/headers. This cookie is NOT httpOnly (client JS has to
// be able to set it) — that's a known interim tradeoff until the backend
// issues its own httpOnly session cookie; don't treat this as XSS-hardened.
export const AUTH_COOKIE_NAME = "fleet_token";
