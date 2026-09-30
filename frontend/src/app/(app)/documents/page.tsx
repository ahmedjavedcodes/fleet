"use client"

import { FileText, Search, UploadCloud } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { useDeleteDocument, useDocuments, useSearchDocuments, useUploadDocument } from "@/lib/api/documents"
import { isApiError } from "@/lib/api/errors"
import { useVehicles } from "@/lib/api/vehicles"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { DOCUMENT_TYPE_LABELS } from "@/lib/enum-labels"
import { can } from "@/lib/rbac"
import type { DocumentResponse, DocumentSearchHit } from "@/lib/schemas/document"
import type { DocumentType } from "@/lib/schemas/enums"
import { CitationHoverCard, CitationPill, CitationSheet } from "@/components/ai/citation-pill"
import { DocumentLibraryTable } from "@/components/ai/document-library-table"
import { DocumentUploadCard } from "@/components/ai/document-upload-card"
import { PageHeader } from "@/components/layout/page-header"
import { SectionPanel } from "@/components/primitives/section-panel"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const NO_VEHICLE = "none"
const ACCEPTED_FILES = ".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
const SEARCH_MIN_LENGTH = 3

// Mirrors the backend: admins may upload every type, fleet managers all but "legal".
function uploadableTypes(role: string | null | undefined): DocumentType[] {
  const all = Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[]
  return role === "admin" ? all : all.filter((t) => t !== "legal")
}

function errorMessage(error: unknown, fallback: string): string {
  return isApiError(error) && "message" in error ? error.message : fallback
}

function UploadPanel({ types }: { types: DocumentType[] }) {
  const vehiclesQuery = useVehicles()
  const upload = useUploadDocument()
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [documentType, setDocumentType] = useState<DocumentType>(types[0]!)
  const [vehicleId, setVehicleId] = useState(NO_VEHICLE)
  const [lastFailure, setLastFailure] = useState<string | null>(null)

  function submit() {
    if (!file) return
    setLastFailure(null)
    upload.mutate(
      { file, document_type: documentType, vehicle_id: vehicleId === NO_VEHICLE ? undefined : vehicleId },
      {
        onSuccess: () => {
          toast.success(`${file.name} uploaded — processing`)
          setFile(null)
          if (fileRef.current) fileRef.current.value = ""
        },
        onError: (error) => setLastFailure(errorMessage(error, "Couldn't upload this document.")),
      }
    )
  }

  return (
    <SectionPanel icon={UploadCloud} title="Upload a document">
      <p className="text-caption text-muted-foreground">
        PDF or plain text. Uploading the same filename and type again replaces the earlier version.
      </p>
      <FieldGroup className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field>
          <FieldLabel htmlFor="document_file">File</FieldLabel>
          <Input
            id="document_file"
            ref={fileRef}
            type="file"
            accept={ACCEPTED_FILES}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="document_type">Type</FieldLabel>
          <Select value={documentType} onValueChange={(v) => setDocumentType(v as DocumentType)}>
            <SelectTrigger id="document_type" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {types.map((t) => (
                <SelectItem key={t} value={t}>
                  {DOCUMENT_TYPE_LABELS[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel htmlFor="document_vehicle">Vehicle (optional)</FieldLabel>
          <Select value={vehicleId} onValueChange={setVehicleId}>
            <SelectTrigger id="document_vehicle" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_VEHICLE}>No vehicle</SelectItem>
              {(vehiclesQuery.data ?? []).map((v) => (
                <SelectItem key={v.id} value={v.id}>
                  {v.plate_number}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </FieldGroup>

      {upload.isPending && file ? <DocumentUploadCard filename={file.name} phase="uploading" /> : null}
      {lastFailure && file ? (
        <DocumentUploadCard filename={file.name} phase="failed" errorMessage={lastFailure} onRetry={submit} />
      ) : null}

      <div className="flex justify-end">
        <Button onClick={submit} disabled={!file || upload.isPending}>
          <UploadCloud className="size-4" />
          Upload
        </Button>
      </div>
    </SectionPanel>
  )
}

function SearchPanel() {
  const search = useSearchDocuments()
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState("")
  const [openHit, setOpenHit] = useState<DocumentSearchHit | null>(null)
  const canSearch = query.trim().length >= SEARCH_MIN_LENGTH

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSearch) return
    setSubmitted(query.trim())
    search.mutate({ query: query.trim() })
  }

  return (
    <SectionPanel icon={Search} title="Search documents">
      <form onSubmit={submit} className="flex gap-2" role="search">
        <Input
          aria-label="Search documents"
          placeholder="Ask about a manual, policy or invoice…"
          value={query}
          maxLength={500}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button type="submit" disabled={!canSearch || search.isPending}>
          <Search className="size-4" />
          Search
        </Button>
      </form>

      {search.isError ? (
        <p role="alert" className="text-caption text-destructive">
          {errorMessage(search.error, "Search failed.")}
        </p>
      ) : null}

      {search.data && search.data.results.length === 0 ? (
        <EmptyState icon={Search} title="No matching passages" description="Nothing in your documents was relevant enough to this search." />
      ) : null}

      {search.data && search.data.results.length > 0 ? (
        <ul className="space-y-2">
          {search.data.results.map((hit) => (
            <li key={`${hit.document_id}-${hit.chunk_index}`} className="rounded-lg border border-border bg-card p-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <CitationHoverCard hit={hit} query={submitted}>
                  <button type="button" onClick={() => setOpenHit(hit)} className="cursor-pointer text-left">
                    <CitationPill hit={hit} />
                  </button>
                </CitationHoverCard>
                <span className="text-caption text-muted-foreground">{Math.round(hit.relevance * 100)}% match</span>
              </div>
              <p className="line-clamp-3 text-sm text-foreground">{hit.text}</p>
            </li>
          ))}
        </ul>
      ) : null}

      {openHit ? (
        <CitationSheet hit={openHit} query={submitted} open onOpenChange={(open) => !open && setOpenHit(null)} />
      ) : null}
    </SectionPanel>
  )
}

export default function DocumentsPage() {
  const { role } = useCurrentUser()
  const canUpload = Boolean(role && can(role, "document:upload"))
  const canDelete = Boolean(role && can(role, "document:delete"))
  const canSearch = Boolean(role && can(role, "document:search"))

  const documentsQuery = useDocuments()
  const vehiclesQuery = useVehicles()
  const deleteMutation = useDeleteDocument()
  const [deleting, setDeleting] = useState<DocumentResponse | undefined>()

  const vehiclePlates = useMemo(
    () => Object.fromEntries((vehiclesQuery.data ?? []).map((v) => [v.id, v.plate_number])),
    [vehiclesQuery.data]
  )

  // Tell the user when a document they uploaded finishes processing, since the
  // table just quietly flips its status pill.
  const previousStatus = useRef<Map<string, string>>(new Map())
  useEffect(() => {
    for (const doc of documentsQuery.data ?? []) {
      const before = previousStatus.current.get(doc.id)
      if (before === "processing" && doc.status === "ready") toast.success(`${doc.filename} is ready to search`)
      if (before === "processing" && doc.status === "failed") toast.error(`${doc.filename} failed to process`)
      previousStatus.current.set(doc.id, doc.status)
    }
  }, [documentsQuery.data])

  function confirmDelete() {
    if (!deleting) return
    const target = deleting
    deleteMutation.mutate(target.id, {
      onSuccess: () => toast.success(`${target.filename} deleted`),
      onError: (error) => toast.error(errorMessage(error, "Couldn't delete this document.")),
    })
    setDeleting(undefined)
  }

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Documents" }]} />

      {canUpload ? <UploadPanel types={uploadableTypes(role)} /> : null}
      {canSearch ? <SearchPanel /> : null}

      <SectionPanel icon={FileText} title="Library">
        <QueryRegion
          query={documentsQuery}
          skeleton={<PageSkeleton />}
          empty={
            <EmptyState
              icon={FileText}
              title="No documents yet"
              description={canUpload ? "Upload a manual, policy or invoice to get started." : "Documents shared with your role will appear here."}
            />
          }
          isEmpty={(rows) => rows.length === 0}
          areaLabel="documents"
        >
          {(rows) => (
            <DocumentLibraryTable documents={rows} vehiclePlates={vehiclePlates} canDelete={canDelete} onDelete={setDeleting} />
          )}
        </QueryRegion>
      </SectionPanel>

      <AlertDialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(undefined)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.filename}?</AlertDialogTitle>
            <AlertDialogDescription>
              It will no longer appear in search results or in the assistant&apos;s answers. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
