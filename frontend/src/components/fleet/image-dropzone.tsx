"use client"

import { ImagePlus, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { IMAGE_UPLOAD_MAX_BYTES, IMAGE_UPLOAD_TYPES } from "@/lib/api/uploads"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

// A single-image picker (click or drag-and-drop) that only holds the chosen
// file — the caller uploads it on submit. JPEG/PNG up to 5 MB, mirroring the
// backend's own checks (the backend stays the authority).
export function ImageDropzone({
  id,
  file,
  onChange,
}: {
  id: string
  file: File | null
  onChange: (file: File | null) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  function accept(candidate: File | undefined) {
    if (!candidate) return
    if (!(IMAGE_UPLOAD_TYPES as readonly string[]).includes(candidate.type)) {
      setError("Only JPEG and PNG images are allowed.")
      return
    }
    if (candidate.size > IMAGE_UPLOAD_MAX_BYTES) {
      setError("Image must be 5 MB or smaller.")
      return
    }
    setError(null)
    onChange(candidate)
  }

  function clear() {
    setError(null)
    onChange(null)
    if (inputRef.current) inputRef.current.value = ""
  }

  return (
    <div className="space-y-2">
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={IMAGE_UPLOAD_TYPES.join(",")}
        className="sr-only"
        onChange={(e) => accept(e.target.files?.[0])}
      />
      {file ? (
        <div className="flex items-center gap-3 rounded-lg border border-border p-2">
          {previewUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- local blob preview, nothing for next/image to optimise
            <img src={previewUrl} alt="Selected attachment preview" className="size-14 rounded-md object-cover" />
          ) : null}
          <p className="min-w-0 flex-1 truncate text-sm text-foreground">{file.name}</p>
          <Button type="button" variant="ghost" size="icon-sm" onClick={clear} aria-label="Remove image">
            <X />
          </Button>
        </div>
      ) : (
        <label
          htmlFor={id}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            accept(e.dataTransfer.files?.[0])
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-1 rounded-lg border border-dashed border-border px-4 py-5 text-center text-sm text-muted-foreground transition-colors hover:bg-muted/50 focus-within:ring-2 focus-within:ring-ring",
            dragging && "border-primary bg-muted/50"
          )}
        >
          <ImagePlus className="size-5" aria-hidden />
          <span>Drag an image here, or click to browse</span>
          <span className="text-caption">JPEG or PNG, up to 5 MB</span>
        </label>
      )}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}
