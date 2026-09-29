"use client"

import { useState } from "react"
import { Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

// Enter sends, Shift+Enter adds a newline; disabled while an approval is
// pending (plans/07 §3). `onStop` is offered whenever `isStreaming` is
// true, aborting via the caller's own AbortController.
export function Composer({
  onSend,
  onStop,
  isStreaming,
  disabled,
  disabledReason,
}: {
  onSend: (text: string) => void
  onStop?: () => void
  isStreaming?: boolean
  disabled?: boolean
  disabledReason?: string
}) {
  const [value, setValue] = useState("")

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue("")
  }

  return (
    <div className="space-y-1.5 border-t border-border p-3">
      <div className="flex items-end gap-2">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={disabled ? (disabledReason ?? "Waiting…") : "Ask something…"}
          disabled={disabled}
          rows={1}
          className="max-h-40 flex-1 resize-none"
        />
        {isStreaming ? (
          <Button type="button" variant="outline" onClick={onStop}>
            <Square className="size-4" />
            Stop
          </Button>
        ) : (
          <Button type="button" onClick={submit} disabled={disabled || value.trim() === ""}>
            Send
          </Button>
        )}
      </div>
      {disabled && disabledReason ? <p className="text-caption text-muted-foreground">{disabledReason}</p> : null}
    </div>
  )
}
