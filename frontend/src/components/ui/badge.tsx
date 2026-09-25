import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { Slot } from "radix-ui"

// Status and severity variants pair a soft background with an AA-contrast text token.
// Color is never the only signal: always render a text label (CLAUDE.md §1.3).
const badgeVariants = cva(
  "group/badge inline-flex h-6 w-fit shrink-0 items-center justify-center gap-1.5 overflow-hidden rounded-full border border-transparent px-2.5 py-0.5 text-caption font-medium whitespace-nowrap transition duration-150 ease-standard focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary-soft text-primary-strong [a]:hover:bg-primary-soft/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        outline:
          "border-border text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary-strong underline-offset-4 hover:underline",
        neutral: "bg-muted text-muted-foreground",
        success: "bg-success-soft text-success-strong",
        warning: "border-warning-border bg-warning-soft text-warning-strong",
        info: "bg-info-soft text-info-strong",
        destructive:
          "bg-destructive-soft text-destructive focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40",
        "sev-minor": "bg-info-soft text-info-strong",
        "sev-moderate": "border-warning-border bg-warning-soft text-warning-strong",
        "sev-severe": "bg-primary-soft text-primary-strong",
        "sev-critical": "bg-destructive-soft text-destructive",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
