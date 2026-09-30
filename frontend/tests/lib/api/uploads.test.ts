import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resolveAttachmentUrl, uploadImage } from "@/lib/api/uploads"

describe("lib/api/uploads", () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  it("posts the file as multipart/form-data and resolves with the returned url", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ url: "/uploads/incidents/abc.jpg" }), { status: 201, headers: { "content-type": "application/json" } })
    )
    const file = new File(["x"], "crash.jpg", { type: "image/jpeg" })

    await expect(uploadImage(file)).resolves.toBe("/uploads/incidents/abc.jpg")

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe("/api/proxy/uploads/image")
    expect(init.method).toBe("POST")
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get("file")).toBeInstanceOf(File)
    expect(init.headers["Content-Type"]).toBeUndefined()
  })

  it("points uploaded paths at the API host and leaves external urls alone", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000")
    expect(resolveAttachmentUrl("/uploads/incidents/abc.jpg")).toBe("http://localhost:8000/uploads/incidents/abc.jpg")
    expect(resolveAttachmentUrl("https://files.example.com/inc-1.jpg")).toBe("https://files.example.com/inc-1.jpg")
  })
})
