import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { MarkdownContent } from "@/components/ai/markdown-content"

const REPLY = [
  "## Overdue services",
  "",
  "Two vehicles need attention: **AB-1234** and *CD-5678*.",
  "",
  "### Details",
  "",
  "- Oil change for AB-1234",
  "- Brake inspection for CD-5678",
  "",
  "1. Book the workshop",
  "2. Notify the driver",
  "",
  "> Check the manual before you start.",
  "",
  "Use `qty_on_hand` to see stock.",
  "",
  "```",
  "SELECT plate FROM vehicles;",
  "```",
  "",
  "| Vehicle | Km left |",
  "|---|---|",
  "| AB-1234 | 250 |",
].join("\n")

describe("MarkdownContent", () => {
  it("renders headings with their own typography, not as unstyled lines", () => {
    render(<MarkdownContent text={REPLY} />)

    const h2 = screen.getByRole("heading", { level: 2, name: "Overdue services" })
    const h3 = screen.getByRole("heading", { level: 3, name: "Details" })
    expect(h2).toHaveClass("font-semibold", "text-base")
    expect(h3).toHaveClass("font-semibold", "text-sm")
  })

  it("renders bulleted and numbered lists with real list styling", () => {
    render(<MarkdownContent text={REPLY} />)

    const bullets = screen.getAllByRole("list")[0]!
    expect(bullets).toHaveClass("list-disc", "pl-5")
    expect(within(bullets).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Oil change for AB-1234", "Brake inspection for CD-5678"])
    const numbered = screen.getAllByRole("list")[1]!
    expect(numbered.tagName).toBe("OL")
    expect(numbered).toHaveClass("list-decimal")
  })

  it("renders bold, italic, quotes and inline code distinctly", () => {
    render(<MarkdownContent text={REPLY} />)

    expect(screen.getByText("AB-1234", { selector: "strong" })).toHaveClass("font-semibold")
    expect(screen.getByText("CD-5678", { selector: "em" })).toBeInTheDocument()
    expect(screen.getByText("Check the manual before you start.").closest("blockquote")).toHaveClass("border-l-2")
    expect(screen.getByText("qty_on_hand")).toHaveClass("bg-muted", "rounded")
  })

  it("renders a fenced block as one code block with a copy button", async () => {
    const user = userEvent.setup() // installs its own clipboard stub; spy on that one
    const writeText = vi.spyOn(navigator.clipboard, "writeText")
    const { container } = render(<MarkdownContent text={REPLY} />)

    expect(container.querySelectorAll("pre")).toHaveLength(1) // not a <pre> inside a <pre>
    expect(container.querySelector("pre")).toHaveTextContent("SELECT plate FROM vehicles;")
    await user.click(screen.getByRole("button", { name: "Copy code" }))
    expect(writeText).toHaveBeenCalledWith("SELECT plate FROM vehicles;")
  })

  it("renders tables (scrolling sideways rather than overflowing) and opens links safely in a new tab", () => {
    render(<MarkdownContent text={REPLY + "\n\nSee [the manual](https://example.com)."} />)

    const table = screen.getByRole("table")
    expect(table.parentElement).toHaveClass("overflow-x-auto")
    expect(within(table).getByRole("columnheader", { name: "Vehicle" })).toBeInTheDocument()
    const link = screen.getByRole("link", { name: "the manual" })
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
  })

  it("keeps the whole reply: nothing is truncated", () => {
    const long = Array.from({ length: 60 }, (_, i) => `- Item number ${i + 1}`).join("\n")
    render(<MarkdownContent text={long} />)

    expect(screen.getAllByRole("listitem")).toHaveLength(60)
    expect(screen.getByText("Item number 60")).toBeInTheDocument()
  })

  it("never renders raw HTML from the model", () => {
    const { container } = render(<MarkdownContent text={'Hello <script>alert(1)</script> <img src=x onerror="alert(1)"> world'} />)

    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img")).toBeNull()
  })
})
