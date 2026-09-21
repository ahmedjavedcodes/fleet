"use client";

// TODO: no backend HTTP endpoint exposes ai_agents (LangGraph FleetCopilot)
// yet — ai_agents/ has no APIRouter today. This is a UI shell only: message
// state and image-attach validation work, but sendMessage has nothing to
// call. Wire it to a real endpoint (e.g. POST /api/v1/copilot/messages) once
// one exists, per CLAUDE.md's "backend/ai_agents communicate via defined
// APIs, not tight coupling" rule.
import { Bot, ImagePlus, Send, X } from "lucide-react";
import { useRef, useState } from "react";

import { ErrorBanner } from "@/components/ui/ErrorBanner";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  imageName?: string;
}

const ACCEPTED_IMAGE_TYPES = ["image/jpeg", "image/png"];

export default function CopilotPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [attachedImage, setAttachedImage] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = (file: File | undefined) => {
    if (!file) return;
    if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
      setError("Only .jpg and .png images are supported.");
      return;
    }
    setError(null);
    setAttachedImage(file);
  };

  const sendMessage = () => {
    if (!draft.trim() && !attachedImage) return;
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", text: draft, imageName: attachedImage?.name },
    ]);
    setDraft("");
    setAttachedImage(null);
    setError("The Copilot agent isn't connected to a backend endpoint yet — this is a UI preview.");
  };

  return (
    <main className="flex min-h-screen flex-col p-8">
      <div className="flex items-center gap-2">
        <Bot className="h-6 w-6" />
        <h1 className="text-2xl font-semibold">Fleet Copilot</h1>
      </div>
      <p className="mt-2 text-sm text-neutral-500">Multi-agent chat workspace — ask about fuel trends, maintenance risk, or upload a document to extract.</p>

      <div className="mt-6 flex flex-1 flex-col rounded-lg border border-neutral-200 dark:border-neutral-800">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.length === 0 ? (
            <p className="text-sm text-neutral-400">No messages yet. Ask a question to get started.</p>
          ) : (
            messages.map((m) => (
              <div key={m.id} className={`max-w-lg rounded-lg px-3 py-2 text-sm ${m.role === "user" ? "ml-auto bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : "bg-neutral-100 dark:bg-neutral-800"}`}>
                {m.text}
                {m.imageName && <p className="mt-1 text-xs opacity-70">📎 {m.imageName}</p>}
              </div>
            ))
          )}
        </div>

        {error && (
          <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">
            <ErrorBanner message={error} />
          </div>
        )}

        {attachedImage && (
          <div className="flex items-center gap-2 border-t border-neutral-200 px-4 py-2 text-xs text-neutral-500 dark:border-neutral-800">
            <span>📎 {attachedImage.name}</span>
            <button onClick={() => setAttachedImage(null)} aria-label="Remove attachment">
              <X className="h-3 w-3" />
            </button>
          </div>
        )}

        <div className="flex items-center gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png"
            className="hidden"
            onChange={(e) => handleFileSelect(e.target.files?.[0])}
          />
          <button onClick={() => fileInputRef.current?.click()} aria-label="Attach image" className="rounded-md p-2 text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800">
            <ImagePlus className="h-4 w-4" />
          </button>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="Ask the Copilot..."
            className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
          <button onClick={sendMessage} className="rounded-md bg-neutral-900 p-2 text-white dark:bg-white dark:text-neutral-900" aria-label="Send">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </main>
  );
}
