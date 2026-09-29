// A dotted vertical timeline with a date column and details (plans/00 §5) —
// content-agnostic: the caller renders each item (maintenance log, trip,
// report, incident, …), this only supplies the connector-line layout.
export function TimelineList<T>({
  items,
  getKey,
  children,
}: {
  items: T[]
  getKey: (item: T) => string
  children: (item: T) => React.ReactNode
}) {
  return (
    <ol className="space-y-4 border-l border-border pl-4">
      {items.map((item) => (
        <li key={getKey(item)} className="relative">
          <span aria-hidden className="absolute top-1.5 -left-4 size-2.5 rounded-full border-2 border-card bg-border" />
          {children(item)}
        </li>
      ))}
    </ol>
  )
}
