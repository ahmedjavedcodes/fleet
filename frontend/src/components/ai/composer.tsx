"use client"

import { useEffect, useRef, useState } from "react"
import { Paperclip, Square, X } from "lucide-react"
import { CHAT_IMAGE_TYPES, IMAGE_UPLOAD_MAX_BYTES } from "@/lib/api/uploads"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

// Enter sends, Shift+Enter adds a newline; disabled while an approval is
// pending (plans/07 §3). `onStop` is offered whenever `isStreaming` is
// true, aborting via the caller's own AbortController.
//
// A photo can be staged with the paperclip and sent with (or instead of) text.
// `onSend` may be async: the text and photo are only cleared once it reports
// success, so a failed upload loses neither.
export function Composer({
  onSend,
  onStop,
  isStreaming,
  disabled,
  disabledReason,
}: {
  onSend: (text: string, image: File | null) => boolean | void | Promise<boolean | void>
  onStop?: () => void
  isStreaming?: boolean
  disabled?: boolean
  disabledReason?: string
}) {
  const [value, setValue] = useState("")
  const [image, setImage] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [imageError, setImageError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!image) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(image)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [image])

  const blocked = Boolean(disabled) || submitting

  function clearImage() {
    setImage(null)
    setImageError(null)
    if (fileInput.current) fileInput.current.value = ""
  }

  function stage(file: File | undefined) {
    if (!file) return
    if (!(CHAT_IMAGE_TYPES as readonly string[]).includes(file.type)) {
      setImageError("Only JPEG, PNG or WebP images can be attached.")
      return
    }
    if (file.size > IMAGE_UPLOAD_MAX_BYTES) {
      setImageError("Images must be 5 MB or smaller.")
      return
    }
    setImageError(null)
    setImage(file)
  }

  async function submit() {
    const trimmed = value.trim()
    if ((!trimmed && !image) || blocked) return
    setSubmitting(true)
    try {
      const ok = await onSend(trimmed, image)
      if (ok !== false) {
        setValue("")
        clearImage()
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="shrink-0 space-y-1.5 border-t border-border p-3">
      {image && previewUrl ? (
        <div className="relative inline-block">
          {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview, nothing for next/image to optimise */}
          <img src={previewUrl} alt={`Attached: ${image.name}`} className="size-16 rounded-lg border border-border object-cover" />
          <button
            type="button"
            onClick={clearImage}
            disabled={submitting}
            aria-label="Remove attached image"
            className="absolute -top-2 -right-2 flex size-5 items-center justify-center rounded-full border border-border bg-card text-foreground shadow-card hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <X className="size-3" />
          </button>
        </div>
      ) : null}
      <div className="flex items-end gap-2">
        <input
          ref={fileInput}
          type="file"
          accept={CHAT_IMAGE_TYPES.join(", ")}
          className="hidden"
          aria-hidden
          tabIndex={-1}
          data-testid="composer-image-input"
          onChange={(e) => stage(e.target.files?.[0])}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Attach an image"
          title="Attach an image"
          disabled={blocked}
          onClick={() => fileInput.current?.click()}
        >
          <Paperclip />
        </Button>
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              void submit()
            }
          }}
          placeholder={disabled ? (disabledReason ?? "Waiting…") : image ? "Add a note about the photo (optional)…" : "Ask something…"}
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
          <Button type="button" onClick={() => void submit()} disabled={blocked || (value.trim() === "" && !image)}>
            {submitting && image ? "Uploading…" : "Send"}
          </Button>
        )}
      </div>
      {imageError ? (
        <p role="alert" className="text-caption text-destructive">
          {imageError}
        </p>
      ) : null}
      {disabled && disabledReason ? <p className="text-caption text-muted-foreground">{disabledReason}</p> : null}
    </div>
  )
}
