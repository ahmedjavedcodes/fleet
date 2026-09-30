"use client"

import { memo, useEffect, useId, useRef, useState } from "react"
import { AtSign, FileText, Paperclip, Square, X } from "lucide-react"
import { CHAT_IMAGE_TYPES, IMAGE_UPLOAD_MAX_BYTES } from "@/lib/api/uploads"
import { DOCUMENT_UPLOAD_MAX_BYTES, PDF_MIME_TYPE, isPdf } from "@/lib/document-types"
import { DOCUMENT_TYPE_LABELS } from "@/lib/enum-labels"
import type { DocumentType } from "@/lib/schemas/enums"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

export type MentionableDocument = { id: string; filename: string; document_type: DocumentType }

/** What a message carries beyond its text and photo: a PDF to upload first, and the documents the user referenced. */
export type ComposerExtras = {
  pdf: { file: File; documentType: DocumentType } | null
  documents: MentionableDocument[]
}

const MAX_SUGGESTIONS = 6
// "@" starts a mention at the start of the text or after whitespace (so an e-mail address never triggers it),
// up to the caret.
const MENTION_AT_CARET = /(^|\s)@([^\s@]{0,60})$/

function detectMention(text: string, caret: number): { start: number; query: string } | null {
  const match = MENTION_AT_CARET.exec(text.slice(0, caret))
  if (!match) return null
  const query = match[2] ?? ""
  return { start: caret - query.length - 1, query }
}

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Enter sends, Shift+Enter adds a newline; disabled while an approval is
// pending (plans/07 §3). `onStop` is offered whenever `isStreaming` is
// true, aborting via the caller's own AbortController.
//
// A photo can be staged with the paperclip and sent with (or instead of) text. So can a PDF, when the caller
// says the user may upload documents (`pdfTypes`): it becomes a document in the library and this message is
// answered from it. Typing "@" opens a list of the documents in `documents`; choosing one puts its name in the
// text and a removable pill above the input, and the message is then answered from that document alone.
// `onSend` may be async: the text and attachments are only cleared once it reports success, so a failed upload
// loses none of them. It gets a third argument only when there is a PDF or a mention.
// Memoised: it owns its own text/attachment state, so while a reply streams (and the page
// re-renders per frame) the composer is left alone as long as its props are stable.
export const Composer = memo(function Composer({
  onSend,
  onStop,
  isStreaming,
  disabled,
  disabledReason,
  documents,
  pdfTypes,
}: {
  onSend: (text: string, image: File | null, extras?: ComposerExtras) => boolean | void | Promise<boolean | void>
  onStop?: () => void
  isStreaming?: boolean
  disabled?: boolean
  disabledReason?: string
  /** Documents that can be @-mentioned (ready ones only). Omit to turn mentions off. */
  documents?: MentionableDocument[]
  /** The document types the user may upload. Omit or leave empty to turn PDF attachments off. */
  pdfTypes?: DocumentType[]
}) {
  const [value, setValue] = useState("")
  const [image, setImage] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [pdf, setPdf] = useState<File | null>(null)
  const [pdfType, setPdfType] = useState<DocumentType | null>(null)
  const [attachError, setAttachError] = useState<string | null>(null)
  const [mentions, setMentions] = useState<MentionableDocument[]>([])
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const pendingCaret = useRef<number | null>(null)
  const listId = useId()

  const canAttachPdf = Boolean(pdfTypes && pdfTypes.length > 0)
  const mentionsEnabled = documents !== undefined

  useEffect(() => {
    if (!image) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(image)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [image])

  // After choosing a document the caret belongs just past the inserted name, once React has written the new text.
  useEffect(() => {
    if (pendingCaret.current === null || !textarea.current) return
    textarea.current.focus()
    textarea.current.setSelectionRange(pendingCaret.current, pendingCaret.current)
    pendingCaret.current = null
  }, [value])

  const blocked = Boolean(disabled) || submitting

  const suggestions =
    mention && mentionsEnabled && !dismissed
      ? (documents ?? [])
          .filter((d) => !mentions.some((m) => m.id === d.id))
          .filter((d) => d.filename.toLowerCase().includes(mention.query.toLowerCase()))
          .slice(0, MAX_SUGGESTIONS)
      : []
  const popupOpen = Boolean(mention && mentionsEnabled && !dismissed && !disabled)
  const optionId = (index: number) => `${listId}-option-${index}`

  function clearAttachments() {
    setImage(null)
    setPdf(null)
    setPdfType(null)
    setAttachError(null)
    if (fileInput.current) fileInput.current.value = ""
  }

  function stage(file: File | undefined) {
    if (!file) return
    if (isPdf(file)) {
      if (!canAttachPdf) {
        setAttachError("Only JPEG, PNG or WebP images can be attached.")
        return
      }
      if (file.size > DOCUMENT_UPLOAD_MAX_BYTES) {
        setAttachError("PDFs must be 20 MB or smaller.")
        return
      }
      setAttachError(null)
      setImage(null)
      setPdf(file)
      setPdfType((current) => current ?? pdfTypes?.[0] ?? null)
      return
    }
    if (!(CHAT_IMAGE_TYPES as readonly string[]).includes(file.type)) {
      setAttachError(canAttachPdf ? "Only JPEG, PNG or WebP images, or PDFs, can be attached." : "Only JPEG, PNG or WebP images can be attached.")
      return
    }
    if (file.size > IMAGE_UPLOAD_MAX_BYTES) {
      setAttachError("Images must be 5 MB or smaller.")
      return
    }
    setAttachError(null)
    setPdf(null)
    setImage(file)
  }

  function updateMention(text: string, caret: number) {
    const next = detectMention(text, caret)
    setMention(next)
    setActiveIndex(0)
    if (next === null) setDismissed(false)
  }

  function choose(doc: MentionableDocument) {
    if (!mention) return
    const caret = textarea.current?.selectionStart ?? value.length
    const token = `@${doc.filename} `
    const text = value.slice(0, mention.start) + token + value.slice(caret)
    pendingCaret.current = mention.start + token.length
    setValue(text)
    setMentions((prev) => (prev.some((m) => m.id === doc.id) ? prev : [...prev, doc]))
    setMention(null)
    setDismissed(false)
  }

  function removeMention(doc: MentionableDocument) {
    setMentions((prev) => prev.filter((m) => m.id !== doc.id))
    setValue((text) => text.replace(`@${doc.filename} `, "").replace(`@${doc.filename}`, ""))
  }

  async function submit() {
    const trimmed = value.trim()
    if ((!trimmed && !image && !pdf) || blocked) return
    setSubmitting(true)
    try {
      const extras: ComposerExtras | undefined =
        pdf || mentions.length > 0 ? { pdf: pdf && pdfType ? { file: pdf, documentType: pdfType } : null, documents: mentions } : undefined
      const ok = extras ? await onSend(trimmed, image, extras) : await onSend(trimmed, image)
      if (ok !== false) {
        setValue("")
        setMentions([])
        setMention(null)
        clearAttachments()
      }
    } finally {
      setSubmitting(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (popupOpen) {
      if (e.key === "Escape") {
        e.preventDefault()
        setDismissed(true)
        return
      }
      if (suggestions.length > 0) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault()
          setActiveIndex((i) => (i + (e.key === "ArrowDown" ? 1 : suggestions.length - 1)) % suggestions.length)
          return
        }
        if ((e.key === "Enter" && !e.shiftKey) || e.key === "Tab") {
          e.preventDefault()
          const doc = suggestions[Math.min(activeIndex, suggestions.length - 1)]
          if (doc) choose(doc)
          return
        }
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void submit()
    }
  }

  const hasContent = value.trim() !== "" || image !== null || pdf !== null

  return (
    // A solid bar that runs to the bottom edge of the chat area: nothing but its own surface
    // beneath the input. The bottom padding grows to the phone home-indicator inset if larger.
    <div data-testid="composer" className="shrink-0 space-y-1.5 border-t border-border bg-card p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      {image && previewUrl ? (
        <div className="relative inline-block">
          {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview, nothing for next/image to optimise */}
          <img src={previewUrl} alt={`Attached: ${image.name}`} className="size-16 rounded-lg border border-border object-cover" />
          <button
            type="button"
            onClick={clearAttachments}
            disabled={submitting}
            aria-label="Remove attached image"
            className="absolute -top-2 -right-2 flex size-5 items-center justify-center rounded-full border border-border bg-card text-foreground shadow-card hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <X className="size-3" />
          </button>
        </div>
      ) : null}

      {pdf ? (
        <div data-testid="pdf-chip" className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted p-2">
          <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 truncate text-sm font-medium text-foreground">{pdf.name}</span>
          <span className="text-caption text-muted-foreground">{formatSize(pdf.size)}</span>
          {pdfTypes && pdfTypes.length > 1 ? (
            <Select value={pdfType ?? pdfTypes[0]} onValueChange={(v) => setPdfType(v as DocumentType)} disabled={submitting}>
              <SelectTrigger size="sm" aria-label="Document type" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {pdfTypes.map((t) => (
                  <SelectItem key={t} value={t}>
                    {DOCUMENT_TYPE_LABELS[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <button
            type="button"
            onClick={clearAttachments}
            disabled={submitting}
            aria-label="Remove attached PDF"
            className="ml-auto flex size-5 items-center justify-center rounded-full border border-border bg-card text-foreground hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <X className="size-3" />
          </button>
        </div>
      ) : null}

      {mentions.length > 0 ? (
        <ul aria-label="Referenced documents" className="flex flex-wrap gap-1.5">
          {mentions.map((doc) => (
            <li
              key={doc.id}
              data-testid="mention-pill"
              className="inline-flex max-w-full items-center gap-1 rounded-full border border-primary/30 bg-primary-soft py-0.5 pr-1 pl-2.5 text-caption text-primary-strong"
            >
              <span className="truncate font-medium">@{doc.filename}</span>
              <button
                type="button"
                onClick={() => removeMention(doc)}
                disabled={submitting}
                aria-label={`Remove @${doc.filename}`}
                className="flex size-4 shrink-0 items-center justify-center rounded-full hover:bg-primary/15 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex items-end gap-2">
        <input
          ref={fileInput}
          type="file"
          accept={[...CHAT_IMAGE_TYPES, ...(canAttachPdf ? [PDF_MIME_TYPE] : [])].join(", ")}
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
          aria-label={canAttachPdf ? "Attach an image or PDF" : "Attach an image"}
          title={canAttachPdf ? "Attach an image or PDF" : "Attach an image"}
          disabled={blocked}
          onClick={() => fileInput.current?.click()}
        >
          <Paperclip />
        </Button>
        <div className="relative flex-1">
          {popupOpen ? (
            <ul
              id={listId}
              role="listbox"
              aria-label="Documents to reference"
              className="absolute bottom-full left-0 z-20 mb-2 max-h-56 w-full overflow-y-auto rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-card sm:max-w-sm"
            >
              {suggestions.length > 0 ? (
                suggestions.map((doc, index) => (
                  <li
                    key={doc.id}
                    id={optionId(index)}
                    role="option"
                    aria-selected={index === activeIndex}
                    // mousedown, not click: the textarea must keep focus (a blur would close the list first).
                    onMouseDown={(e) => {
                      e.preventDefault()
                      choose(doc)
                    }}
                    onMouseEnter={() => setActiveIndex(index)}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm",
                      index === activeIndex ? "bg-accent text-accent-foreground" : "text-foreground"
                    )}
                  >
                    <AtSign className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{doc.filename}</span>
                    <Badge variant="outline">{DOCUMENT_TYPE_LABELS[doc.document_type]}</Badge>
                  </li>
                ))
              ) : (
                <li role="presentation" className="px-2 py-1.5 text-sm text-muted-foreground">
                  {(documents ?? []).length === 0 ? "No documents in your library yet." : "No matching documents."}
                </li>
              )}
            </ul>
          ) : null}
          <Textarea
            ref={textarea}
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              setDismissed(false)
              if (mentionsEnabled) updateMention(e.target.value, e.target.selectionStart)
            }}
            onClick={(e) => mentionsEnabled && updateMention(e.currentTarget.value, e.currentTarget.selectionStart)}
            onKeyUp={(e) => {
              if (mentionsEnabled && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
                updateMention(e.currentTarget.value, e.currentTarget.selectionStart)
              }
            }}
            onBlur={() => setDismissed(true)}
            onKeyDown={onKeyDown}
            aria-haspopup={mentionsEnabled ? "listbox" : undefined}
            aria-controls={popupOpen ? listId : undefined}
            aria-activedescendant={popupOpen && suggestions.length > 0 ? optionId(Math.min(activeIndex, suggestions.length - 1)) : undefined}
            placeholder={
              disabled
                ? (disabledReason ?? "Waiting…")
                : pdf
                  ? "Ask about this document (optional)…"
                  : image
                    ? "Add a note about the photo (optional)…"
                    : mentionsEnabled
                      ? "Ask something… (type @ to reference a document)"
                      : "Ask something…"
            }
            disabled={disabled}
            rows={1}
            className="max-h-40 w-full resize-none"
          />
        </div>
        {isStreaming ? (
          <Button type="button" variant="outline" onClick={onStop}>
            <Square className="size-4" />
            Stop
          </Button>
        ) : (
          <Button type="button" onClick={() => void submit()} disabled={blocked || !hasContent}>
            {submitting && (image || pdf) ? "Uploading…" : "Send"}
          </Button>
        )}
      </div>
      {attachError ? (
        <p role="alert" className="text-caption text-destructive">
          {attachError}
        </p>
      ) : null}
      {disabled && disabledReason ? <p className="text-caption text-muted-foreground">{disabledReason}</p> : null}
    </div>
  )
})
