import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { DocumentUploadCard } from "@/components/ai/document-upload-card"

describe("DocumentUploadCard", () => {
  it("shows a progress bar and percentage while uploading", () => {
    render(<DocumentUploadCard filename="manual.pdf" phase="uploading" uploadProgress={42} />)
    expect(screen.getByText("Uploading… 42%")).toBeInTheDocument()
  })

  it("shows the stepped indicator with the current step highlighted while processing", () => {
    render(<DocumentUploadCard filename="manual.pdf" phase="summarizing_tables" />)
    expect(screen.getByText("Extracting")).toBeInTheDocument()
    expect(screen.getByText("Summarizing tables")).toBeInTheDocument()
    expect(screen.getByText("Embedding")).toBeInTheDocument()
    expect(screen.getByText("Ready")).toBeInTheDocument()
  })

  it("shows the error message and a Retry button on failure, calling onRetry when clicked", () => {
    const onRetry = vi.fn()
    render(<DocumentUploadCard filename="manual.pdf" phase="failed" errorMessage="File too large" onRetry={onRetry} />)
    expect(screen.getByText("File too large")).toBeInTheDocument()
    screen.getByRole("button", { name: "Retry" }).click()
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
