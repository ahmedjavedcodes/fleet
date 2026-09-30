import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, describe, expect, it, vi } from "vitest"
import { ImageDropzone } from "@/components/fleet/image-dropzone"

beforeAll(() => {
  URL.createObjectURL = vi.fn(() => "blob:preview")
  URL.revokeObjectURL = vi.fn()
})

function image(name: string, type: string, size = 1024) {
  return new File([new Uint8Array(size)], name, { type })
}

describe("ImageDropzone", () => {
  it("accepts a JPEG or PNG chosen through the picker", async () => {
    const onChange = vi.fn()
    render(<ImageDropzone id="pic" file={null} onChange={onChange} />)
    const input = screen.getByLabelText(/drag an image here/i)
    expect(input).toHaveAttribute("accept", "image/jpeg,image/png")

    const png = image("crash.png", "image/png")
    await userEvent.upload(input, png)
    expect(onChange).toHaveBeenCalledWith(png)
  })

  it("accepts a dropped image", () => {
    const onChange = vi.fn()
    render(<ImageDropzone id="pic" file={null} onChange={onChange} />)
    const jpeg = image("crash.jpg", "image/jpeg")
    fireEvent.drop(screen.getByText(/drag an image here/i), { dataTransfer: { files: [jpeg] } })
    expect(onChange).toHaveBeenCalledWith(jpeg)
  })

  it("rejects unsupported types and oversized files with a message", () => {
    const onChange = vi.fn()
    render(<ImageDropzone id="pic" file={null} onChange={onChange} />)
    const zone = screen.getByText(/drag an image here/i)

    fireEvent.drop(zone, { dataTransfer: { files: [image("anim.gif", "image/gif")] } })
    expect(screen.getByRole("alert")).toHaveTextContent("Only JPEG and PNG")

    fireEvent.drop(zone, { dataTransfer: { files: [image("huge.jpg", "image/jpeg", 5 * 1024 * 1024 + 1)] } })
    expect(screen.getByRole("alert")).toHaveTextContent("5 MB or smaller")
    expect(onChange).not.toHaveBeenCalled()
  })

  it("shows the chosen file with a preview and lets the user remove it", async () => {
    const onChange = vi.fn()
    render(<ImageDropzone id="pic" file={image("crash.jpg", "image/jpeg")} onChange={onChange} />)
    expect(screen.getByText("crash.jpg")).toBeInTheDocument()
    expect(screen.getByAltText("Selected attachment preview")).toHaveAttribute("src", "blob:preview")

    await userEvent.click(screen.getByRole("button", { name: "Remove image" }))
    expect(onChange).toHaveBeenCalledWith(null)
  })
})
