"use client"

import { useQueryClient } from "@tanstack/react-query"
import { ChevronsUpDown, LogOut } from "lucide-react"
import { useRouter } from "next/navigation"
import { logout } from "@/lib/api/auth"
import { roleLabel } from "@/lib/auth/role-labels"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { Badge } from "@/components/ui/badge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { InitialsAvatar } from "@/components/primitives/initials-avatar"

// The sidebar's bottom user card, which is also the user menu's trigger
// (there is no separate topbar avatar — CLAUDE.md §3). *Profile* is
// intentionally not an item here: there is no profile page or endpoint
// beyond /auth/me yet (CLAUDE.md §3, "no dead UI" — CLAUDE.md §7).
export function UserMenu({ collapsed = false }: { collapsed?: boolean }) {
  const { user, role, organization, isPending } = useCurrentUser()
  const router = useRouter()
  const queryClient = useQueryClient()

  async function handleSignOut() {
    await logout()
    queryClient.clear()
    router.push("/login")
  }

  if (isPending || !user || !role) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-border p-3">
        <Skeleton className="size-8 shrink-0 rounded-full" />
        {!collapsed && (
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>
        )}
      </div>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition duration-150 ease-standard hover:bg-muted focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <InitialsAvatar fullName={user.full_name} />
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-foreground">{user.full_name}</span>
                <span className="block truncate text-caption text-muted-foreground">{roleLabel(role)}</span>
              </span>
              <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel>
          <span className="block truncate font-medium">{user.full_name}</span>
          <span className="mt-1 flex items-center gap-1.5">
            <Badge variant="neutral">{roleLabel(role)}</Badge>
            <span className="truncate text-caption font-normal text-muted-foreground">{organization?.name}</span>
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void handleSignOut()}>
          <LogOut aria-hidden />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
