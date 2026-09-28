import { Card } from "@/components/ui/card"

// The white bordered card nested inside a SectionPanel's grey background
// ("Scheduled Service" in the reference — plans/00 §5). A thin semantic
// alias over Card's compact size so call sites read like the design
// vocabulary instead of every SectionPanel child re-deriving `size="sm"`.
export function InnerCard(props: Omit<React.ComponentProps<typeof Card>, "size">) {
  return <Card size="sm" {...props} />
}
