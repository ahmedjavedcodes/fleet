import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { AgentActivity, ApprovalCard, HaltedCard } from "@/components/ai/agent-panels"
import { ChatThread } from "@/components/ai/chat-thread"
import { Composer } from "@/components/ai/composer"
import { MessageBubble } from "@/components/ai/message-bubble"
import type { ChatMessage } from "@/lib/schemas/chat"

describe("MessageBubble", () => {
  it("renders markdown text and opens links in a new tab safely", () => {
    render(<MessageBubble message={{ id: "1", role: "assistant", text: "See [docs](https://example.com)." }} />)
    const link = screen.getByRole("link", { name: "docs" })
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
  })

  it("renders citation pills when the message has citations", () => {
    const message: ChatMessage = {
      id: "2",
      role: "assistant",
      text: "Per the manual.",
      citations: [{ document_id: "d1", filename: "manual.pdf", document_type: "manual", chunk_index: 0, text: "x", relevance: 0.5 }],
    }
    render(<MessageBubble message={message} />)
    expect(screen.getByText("manual.pdf")).toBeInTheDocument()
  })
})

describe("ChatThread", () => {
  it("renders every message", () => {
    const messages: ChatMessage[] = [
      { id: "1", role: "user", text: "Hi" },
      { id: "2", role: "assistant", text: "Hello" },
    ]
    render(<ChatThread messages={messages} />)
    expect(screen.getByText("Hi")).toBeInTheDocument()
    expect(screen.getByText("Hello")).toBeInTheDocument()
  })
})

describe("Composer", () => {
  it("sends on Enter and adds a newline on Shift+Enter, and clears after send", () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)
    const textarea = screen.getByPlaceholderText("Ask something…")
    fireEvent.change(textarea, { target: { value: "hello" } })
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()
    fireEvent.keyDown(textarea, { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("hello", null)
  })

  it("stages an image from the paperclip, previews it, and the X clears it", async () => {
    URL.createObjectURL = vi.fn(() => "blob:preview")
    URL.revokeObjectURL = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={vi.fn()} />)

    const input = screen.getByTestId("composer-image-input")
    expect(input).toHaveAttribute("accept", "image/jpeg, image/png, image/webp")
    expect(screen.getByRole("button", { name: "Attach an image" })).toBeInTheDocument()

    await user.upload(input, new File(["x"], "receipt.webp", { type: "image/webp" }))
    expect(screen.getByAltText("Attached: receipt.webp")).toHaveAttribute("src", "blob:preview")

    await user.click(screen.getByRole("button", { name: "Remove attached image" }))
    expect(screen.queryByAltText("Attached: receipt.webp")).not.toBeInTheDocument()
  })

  it("rejects non-image and oversized files without staging them", () => {
    render(<Composer onSend={vi.fn()} />)
    const input = screen.getByTestId("composer-image-input")

    fireEvent.change(input, { target: { files: [new File(["x"], "notes.pdf", { type: "application/pdf" })] } })
    expect(screen.getByRole("alert")).toHaveTextContent("Only JPEG, PNG or WebP")

    fireEvent.change(input, { target: { files: [new File([new Uint8Array(5 * 1024 * 1024 + 1)], "huge.png", { type: "image/png" })] } })
    expect(screen.getByRole("alert")).toHaveTextContent("5 MB or smaller")
    expect(screen.queryByAltText(/Attached:/)).not.toBeInTheDocument()
  })

  it("keeps the text when the parent reports the send failed", async () => {
    const user = userEvent.setup()
    render(<Composer onSend={() => Promise.resolve(false)} />)
    await user.type(screen.getByPlaceholderText("Ask something…"), "retry me")
    await user.click(screen.getByRole("button", { name: "Send" }))
    expect(screen.getByDisplayValue("retry me")).toBeInTheDocument()
  })

  it("disables the input and shows the reason when disabled", () => {
    render(<Composer onSend={vi.fn()} disabled disabledReason="Waiting on approval" />)
    expect(screen.getByPlaceholderText("Waiting on approval")).toBeDisabled()
    expect(screen.getByText("Waiting on approval")).toBeInTheDocument()
  })

  it("shows Stop instead of Send while streaming", () => {
    const onStop = vi.fn()
    render(<Composer onSend={vi.fn()} isStreaming onStop={onStop} />)
    screen.getByRole("button", { name: /stop/i }).click()
    expect(onStop).toHaveBeenCalledOnce()
  })
})

describe("AgentActivity", () => {
  it("renders a step per agent with done/active state", () => {
    render(
      <AgentActivity
        steps={[
          { agent: "fuel", step: "Checking fuel logs", done: true },
          { agent: "maintenance", step: "Checking maintenance", done: false },
        ]}
      />
    )
    expect(screen.getByText("Checking fuel logs")).toBeInTheDocument()
    expect(screen.getByText("Checking maintenance")).toBeInTheDocument()
  })
})

describe("ApprovalCard", () => {
  const hitlState = { agent_name: "assignment", thread_id: "t1", tool_name: "Assign driver X", approval_prompt: "Approve this assignment?" }

  it("never auto-approves — Approve requires an explicit click", () => {
    const onApprove = vi.fn()
    render(<ApprovalCard hitlState={hitlState} onApprove={onApprove} onModify={vi.fn()} onReject={vi.fn()} />)
    expect(onApprove).not.toHaveBeenCalled()
    screen.getByRole("button", { name: "Approve" }).click()
    expect(onApprove).toHaveBeenCalledOnce()
  })

  it("confirms before calling onReject", () => {
    const onReject = vi.fn()
    render(<ApprovalCard hitlState={hitlState} onApprove={vi.fn()} onModify={vi.fn()} onReject={onReject} />)
    fireEvent.click(screen.getByRole("button", { name: "Reject" }))
    expect(onReject).not.toHaveBeenCalled()
    expect(screen.getByText("Reject this action?")).toBeInTheDocument()
    const rejectButtons = screen.getAllByRole("button", { name: "Reject" })
    fireEvent.click(rejectButtons[rejectButtons.length - 1]!)
    expect(onReject).toHaveBeenCalledOnce()
  })

  it("lets Modify submit free-text notes", () => {
    const onModify = vi.fn()
    render(<ApprovalCard hitlState={hitlState} onApprove={vi.fn()} onModify={onModify} onReject={vi.fn()} />)
    fireEvent.click(screen.getByRole("button", { name: "Modify" }))
    fireEvent.change(screen.getByPlaceholderText("Describe the change…"), { target: { value: "use a different driver" } })
    fireEvent.click(screen.getByRole("button", { name: "Submit change" }))
    expect(onModify).toHaveBeenCalledWith("use a different driver")
  })
})

describe("HaltedCard", () => {
  it("renders the halt reason as a warning, not an error", () => {
    render(<HaltedCard reason="Needed a vehicle ID that wasn't provided." />)
    expect(screen.getByText("Needed a vehicle ID that wasn't provided.")).toBeInTheDocument()
  })
})
