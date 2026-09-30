import { useMutation } from "@tanstack/react-query"
import { z } from "zod"
import { apiRequest } from "./client"

export const IMAGE_UPLOAD_TYPES = ["image/jpeg", "image/png"] as const
// The chat also takes WebP: the backend stores it, and the chat server converts
// it to PNG before a vision model reads it.
export const CHAT_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"] as const
export const IMAGE_UPLOAD_MAX_BYTES = 5 * 1024 * 1024

const imageUploadResponseSchema = z.object({ url: z.string().min(1) })

// Multipart. Resolves with the site-relative path the API host serves the image from.
export function uploadImage(file: File): Promise<string> {
  const formData = new FormData()
  formData.append("file", file)
  return apiRequest("/uploads/image", { method: "POST", body: formData, schema: imageUploadResponseSchema }).then((r) => r.url)
}

export function useUploadImage() {
  return useMutation({ mutationFn: uploadImage })
}

// Uploaded images are stored as "/uploads/…" paths on the API host, which the
// browser must reach directly (the /api/proxy route is for JSON calls). Older
// incidents hold a full external URL, which passes through untouched.
export function resolveAttachmentUrl(url: string): string {
  if (!url.startsWith("/")) return url
  return `${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}${url}`
}
