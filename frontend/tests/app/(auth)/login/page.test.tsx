import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { login } from "@/lib/api/auth"
import LoginPage from "@/app/(auth)/login/page"

let mockSearch = ""
const replace = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(mockSearch),
}))

vi.mock("@/lib/api/auth", () => ({
  login: vi.fn(),
}))

function renderPage() {
  const queryClient = new QueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <LoginPage />
    </QueryClientProvider>
  )
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, values: Partial<Record<"org" | "email" | "password", string>> = {}) {
  const { org = "acme", email = "a@acme.dev", password = "secret123" } = values
  if (org) await user.type(screen.getByLabelText(/organization/i), org)
  if (email) await user.type(screen.getByLabelText(/email/i), email)
  if (password) await user.type(screen.getByLabelText(/password/i), password)
  await user.click(screen.getByRole("button", { name: /sign in/i }))
}

describe("LoginPage", () => {
  beforeEach(() => {
    replace.mockClear()
    vi.mocked(login).mockReset()
    mockSearch = ""
  })

  it("shows validation errors on an empty submit and never calls login", async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole("button", { name: /sign in/i }))

    expect(await screen.findByText(/organization is required/i)).toBeInTheDocument()
    expect(screen.getByText(/email is required/i)).toBeInTheDocument()
    expect(screen.getByText(/password is required/i)).toBeInTheDocument()
    expect(login).not.toHaveBeenCalled()
  })

  it("rejects an organization slug with invalid characters", async () => {
    const user = userEvent.setup()
    renderPage()
    await fillAndSubmit(user, { org: "Not A Slug!" })
    expect(await screen.findByText(/lowercase letters, numbers and hyphens/i)).toBeInTheDocument()
    expect(login).not.toHaveBeenCalled()
  })

  it("shows a single generic message on 401, never hinting which field was wrong", async () => {
    vi.mocked(login).mockRejectedValue({ kind: "unauthorized", status: 401 })
    const user = userEvent.setup()
    renderPage()
    await fillAndSubmit(user, { password: "wrongpassword" })

    expect(await screen.findByText(/invalid organization, email or password/i)).toBeInTheDocument()
  })

  it("maps 422 field errors from the backend onto the matching field", async () => {
    vi.mocked(login).mockRejectedValue({
      kind: "validation",
      status: 422,
      message: "Request failed (422).",
      fieldErrors: { org_slug: "Organization not found" },
    })
    const user = userEvent.setup()
    renderPage()
    await fillAndSubmit(user, { org: "unknown-org" })

    expect(await screen.findByText(/organization not found/i)).toBeInTheDocument()
  })

  it("redirects to /dashboard on success when there is no next=", async () => {
    vi.mocked(login).mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()
    await fillAndSubmit(user)

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"))
  })

  it("redirects to a safe next= on success", async () => {
    mockSearch = "next=%2Ffoundation%2Fvehicles"
    vi.mocked(login).mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()
    await fillAndSubmit(user)

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/foundation/vehicles"))
  })

  it("falls back to /dashboard when next= is an open-redirect attempt", async () => {
    mockSearch = `next=${encodeURIComponent("https://evil.example.com")}`
    vi.mocked(login).mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()
    await fillAndSubmit(user)

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"))
  })

  it("disables the submit button while the request is pending", async () => {
    let resolveLogin: () => void = () => {}
    vi.mocked(login).mockReturnValue(
      new Promise((resolve) => {
        resolveLogin = () => resolve(undefined)
      })
    )
    const user = userEvent.setup()
    renderPage()
    await fillAndSubmit(user)

    expect(screen.getByRole("button", { name: /sign in/i })).toBeDisabled()
    resolveLogin()
  })
})
