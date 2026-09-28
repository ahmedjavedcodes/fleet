import Link from "next/link"
import { Fragment } from "react"
import { cn } from "@/lib/utils"
import {
  Breadcrumb,
  BreadcrumbEllipsis,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

export type Crumb = { label: string; href?: string }

// The topbar trail, last crumb bold (plans/00 §5). Middle crumbs collapse
// to an ellipsis below `sm` so a deep trail never wraps or overflows on a
// driver's phone (plans/03 §4).
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  const hasMiddle = items.length > 2

  return (
    <Breadcrumb>
      <BreadcrumbList className="flex-nowrap">
        {items.map((item, index) => {
          const isFirst = index === 0
          const isLast = index === items.length - 1
          const isMiddle = !isFirst && !isLast

          return (
            <Fragment key={item.href ?? item.label}>
              {!isFirst && <BreadcrumbSeparator className={isMiddle ? "hidden sm:flex" : undefined} />}
              {isMiddle && index === 1 && hasMiddle && (
                <>
                  <BreadcrumbEllipsis className="sm:hidden" />
                  <BreadcrumbSeparator className="sm:hidden" />
                </>
              )}
              <BreadcrumbItem className={cn("min-w-0", isMiddle && "hidden sm:inline-flex")}>
                {isLast || !item.href ? (
                  <BreadcrumbPage className="truncate font-semibold text-foreground">{item.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild className="truncate">
                    <Link href={item.href}>{item.label}</Link>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
            </Fragment>
          )
        })}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
