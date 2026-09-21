import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-neutral-300 p-12 text-center dark:border-neutral-700">
      <Icon className="h-8 w-8 text-neutral-400" />
      <p className="font-medium text-neutral-700 dark:text-neutral-200">{title}</p>
      {description && <p className="max-w-sm text-sm text-neutral-500">{description}</p>}
      {action}
    </div>
  );
}
