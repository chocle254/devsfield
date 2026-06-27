"use client"

import { useEffect, useRef, useState } from "react"
import type { EditMessage, RunResult } from "@/lib/types"

const SUGGESTIONS = [
  "Remove the closing scene",
  "Make the narration more energetic",
  "Add a scene about the tech stack",
  "Make it shorter",
]

export function EditChat({
  id,
  result,
  onResult,
}: {
  id: string
  result: RunResult
  onResult: (r: RunResult) => void
}) {
  const [input, setInput] = useState("")
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const messages = result.edits

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages.length, sending])

  async function send(text: string) {
    const instruction = text.trim()
    if (!instruction || sending) return
    setInput("")
    setSending(true)
    setError(null)
    try {
      const res = await fetch(`/api/edit/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }),
      })
      if (!res.ok) throw new Error("Edit failed")
      const data: { result: RunResult } = await res.json()
      onResult(data.result)
    } catch {
      setError("Couldn't apply that edit. Try rephrasing.")
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <WandIcon />
          </span>
          <div>
            <h2 className="text-sm font-semibold leading-tight">Edit with chat</h2>
            <p className="font-mono text-[10px] text-muted-foreground">v{result.version} · targeted edits</p>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="rounded-lg border border-border bg-background/40 p-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              Your demo is ready. Tell me what to change and I&apos;ll re-render only the affected
              scene — the rest of the video stays exactly as it is.
            </p>
          </div>
        )}

        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}

        {sending && (
          <div className="flex justify-start">
            <div className="inline-flex items-center gap-2 rounded-2xl rounded-bl-sm border border-border bg-background/60 px-3 py-2">
              <TypingDots />
              <span className="font-mono text-[11px] text-muted-foreground">re-rendering scene…</span>
            </div>
          </div>
        )}

        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>

      {/* Suggestions */}
      {messages.length === 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-3">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              disabled={sending}
              className="rounded-full border border-border bg-background/40 px-3 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
        className="flex items-end gap-2 border-t border-border p-3"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
          rows={1}
          placeholder="e.g. Remove the intro, or make it more technical"
          className="max-h-28 min-h-[42px] flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/50"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          aria-label="Send edit"
          className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          <SendIcon />
        </button>
      </form>
    </div>
  )
}

function MessageBubble({ message }: { message: EditMessage }) {
  const isUser = message.role === "user"
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={[
          "max-w-[88%] rounded-2xl px-3 py-2 text-xs leading-relaxed",
          isUser
            ? "rounded-br-sm bg-primary text-primary-foreground"
            : "rounded-bl-sm border border-border bg-background/60 text-foreground",
        ].join(" ")}
      >
        <p className="whitespace-pre-line">{message.text}</p>
        {message.patch && message.patch.changedAssets.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1 border-t border-border/60 pt-2">
            {message.patch.changedAssets.map((a) => (
              <span
                key={a}
                className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 font-mono text-[10px] text-primary"
              >
                ↻ {a}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TypingDots() {
  return (
    <span className="flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}

function WandIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m3 21 9-9" />
      <path d="M15 4V2M15 10V8M9.5 5.5 8 4M21.5 5.5 20 7M18 6l1-1" />
      <path d="M14 7s2-2 4 0-0 4 0 4" opacity="0.5" />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
    </svg>
  )
}
