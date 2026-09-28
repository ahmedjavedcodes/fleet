import { NextResponse } from "next/server"
import { clearServerToken } from "@/lib/auth/session"

// The backend has no logout endpoint (no refresh token to revoke) — signing
// out is purely a matter of deleting our own session cookie (plans/02 §3).

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST() {
  await clearServerToken()
  return new NextResponse(null, { status: 204 })
}
