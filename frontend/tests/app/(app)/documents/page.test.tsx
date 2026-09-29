import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import DocumentsPage from "@/app/(app)/documents/page"
import { renderWithProviders as render } from "../../../test-utils"

describe("DocumentsPage", () => {
  it("renders NotAvailableYet and never renders the document library table", () => {
    render(<DocumentsPage />)
    expect(screen.getByText("The document library isn't available yet")).toBeInTheDocument()
    expect(screen.queryByRole("table")).not.toBeInTheDocument()
  })
})
