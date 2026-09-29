"use client"

import { Check, FileWarning, Loader2, UploadCloud } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"

export type UploadPhase = "idle" | "uploading" | "extracting" | "summarizing_tables" | "embedding" | "ready" | "failed"

const STEPS: { phase: UploadPhase; label: string }[] = [
  { phase: "extracting", label: "Extracting" },
  { phase: "summarizing_tables", label: "Summarizing tables" },
  { phase: "embedding", label: "Embedding" },
  { phase: "ready", label: "Ready" },
]
const STEP_ORDER = STEPS.map((s) => s.phase)

// The upload flow's transfer + processing UI (plans/07 §2.2) — entirely
// prop-driven (`phase`, `uploadProgress`), no XMLHttpRequest or polling
// inside it. The real version wires those against `/documents/upload` and
// `GET /documents/{id}` once that endpoint exists; today this only renders
// in tests / fixture stories.
export function DocumentUploadCard({
  filename,
  phase,
  uploadProgress,
  errorMessage,
  onRetry,
}: {
  filename: string
  phase: UploadPhase
  uploadProgress?: number
  errorMessage?: string
  onRetry?: () => void
}) {
  const currentIndex = STEP_ORDER.indexOf(phase)

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <UploadCloud className="size-4 text-muted-foreground" aria-hidden />
        <p className="truncate text-sm font-medium text-foreground">{filename}</p>
      </div>

      {phase === "uploading" ? (
        <div className="space-y-1.5">
          <Progress value={uploadProgress ?? 0} />
          <p className="text-caption text-muted-foreground">Uploading… {uploadProgress ?? 0}%</p>
        </div>
      ) : phase === "failed" ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive-soft p-3">
          <div className="flex items-center gap-2">
            <FileWarning className="size-4 shrink-0 text-destructive" aria-hidden />
            <p className="text-caption text-foreground">{errorMessage ?? "Something went wrong."}</p>
          </div>
          {onRetry ? (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          ) : null}
        </div>
      ) : (
        <ol aria-label="Processing steps (indicative)" className="flex flex-wrap gap-3 text-caption">
          {STEPS.map((step, i) => {
            const done = currentIndex > i || phase === "ready"
            const active = STEP_ORDER[currentIndex] === step.phase && !done
            return (
              <li key={step.phase} className={cn("flex items-center gap-1.5", done ? "text-foreground" : active ? "text-primary-strong" : "text-muted-foreground")}>
                {done ? <Check className="size-3.5" aria-hidden /> : active ? <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
                {step.label}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
