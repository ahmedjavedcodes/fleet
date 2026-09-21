"use client";

import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="flex-1">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="shrink-0 font-medium underline underline-offset-2">
          Retry
        </button>
      )}
      <button onClick={() => setDismissed(true)} aria-label="Dismiss" className="shrink-0">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
