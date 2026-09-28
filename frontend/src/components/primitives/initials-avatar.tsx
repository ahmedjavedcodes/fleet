import { Avatar, AvatarFallback } from "@/components/ui/avatar"

export function getInitials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase()
  return (parts[0]![0] + parts[parts.length - 1]![0]).toUpperCase()
}

// User card and driver avatars (plans/00 §5) — there is no photo field on
// User or Driver, so this is always the fallback, never AvatarImage.
export function InitialsAvatar({
  fullName,
  size = "default",
  className,
}: {
  fullName: string
  size?: "sm" | "default" | "lg"
  className?: string
}) {
  return (
    <Avatar size={size} className={className}>
      <AvatarFallback className="bg-primary-soft text-primary-strong">{getInitials(fullName)}</AvatarFallback>
    </Avatar>
  )
}
