import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { logout } from "@/lib/api/auth"
import { UserMenu } from "@/components/layout/user-menu"

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({
  useCurrentUser: () => mockUseCurrentUser(),
}))

vi.mock("@/lib/api/auth", () => ({ logout: vi.fn() }))

const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}))

function renderMenu(queryClient = new QueryClient()) {
  return { queryClient, ...render(
    <QueryClientProvider client={queryClient}>
      <UserMenu />
    </QueryClientProvider>
  ) }
}

describe("UserMenu", () => {
  beforeEach(() => {
    push.mockClear()
    vi.mocked(logout).mockReset().mockResolvedValue(undefined)
    mockUseCurrentUser.mockReturnValue({
      isPending: false,
      user: { full_name: "Test Admin", email: "admin@example.com" },
      role: "admin",
      organization: { name: "Fleet Registry Agent Test Org" },
    })
  })

  it("shows a skeleton while the session is loading", () => {
    mockUseCurrentUser.mockReturnValue({ isPending: true, user: null, role: null, organization: null })
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <UserMenu />
      </QueryClientProvider>
    )
    expect(container.querySelector('[data-slot="skeleton"]')).toBeTruthy()
  })

  it("shows the user's name and role on the closed trigger", () => {
    renderMenu()
    expect(screen.getByText("Test Admin")).toBeInTheDocument()
    expect(screen.getByText("Admin")).toBeInTheDocument()
  })

  it("opens to show name, role badge and org name", async () => {
    const user = userEvent.setup()
    renderMenu()
    await user.click(screen.getByRole("button", { name: /test admin/i }))
    expect(await screen.findByText("Fleet Registry Agent Test Org")).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: /sign out/i })).toBeInTheDocument()
  })

  it("Sign out calls logout and clears the query cache before navigating", async () => {
    const queryClient = new QueryClient()
    const clearSpy = vi.spyOn(queryClient, "clear")
    const user = userEvent.setup()
    renderMenu(queryClient)
    await user.click(screen.getByRole("button", { name: /test admin/i }))
    await user.click(await screen.findByRole("menuitem", { name: /sign out/i }))

    expect(logout).toHaveBeenCalledTimes(1)
    expect(clearSpy).toHaveBeenCalledTimes(1)
    expect(push).toHaveBeenCalledWith("/login")
  })
})
