"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { STEP_DEFS } from "@/lib/steps"
import type { StepId, StepStatus, StreamEvent } from "@/lib/types"

export function PipelineView({ id }: { id: string }) {
  const router = useRouter()
  const [event, setEvent] = useState<StreamEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const redirected = useRef(false)

  useEffect(() => {
    const es = new EventSource(`/api/stream/${id}`)

    es.onmessage = (e) => {
      let payload: StreamEvent
      try {
        payload = JSON.parse(e.data)
      } catch {
        return
      }

      // The backend sends `error` on every event (usually null); only a
      // truthy value with no status indicates a hard failure like "not found".
      if (payload.error && !payload.status) {
        setError(payload.error)
        es.close()
        return
      }

      setEvent(payload)

      if (payload.status === "failed") {
        setError(payload.error || "The pipeline failed. Please try again.")
        es.close()
        return
      }

      if (payload.status === "complete" && !redirected.current) {
        redirected.current = true
        es.close()
        setTimeout(() => router.push(`/result/${id}`), 900)
      }
    }

    es.onerror = () => es.close()
    return () => es.close()
  }, [id, router])

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card p-8 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
      </div>
    )
  }

  const completed = new Set<StepId>(event?.steps_completed ?? [])
  const currentStep = event?.current_step ?? null
  const isComplete = event?.status === "complete"
  const doneCount = isComplete ? STEP_DEFS.length : completed.size
  const progress = Math.round((doneCount / STEP_DEFS.length) * 100)

  return (
    <div className="w-full">
      <div className="mb-6 flex items-center justify-between gap-4">
        <p className="truncate font-mono text-xs text-muted-foreground">
          {event?.message ?? (event ? "working…" : "connecting to pipeline…")}
        </p>
        <span className="shrink-0 font-mono text-xs text-primary">{progress}%</span>
      </div>

      <div className="mb-8 h-1 w-full overflow-hidden rounded-full bg-input">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>

      <ol className="relative">
        {STEP_DEFS.map((def, i) => {
          const status: StepStatus =
            isComplete || completed.has(def.id)
              ? "done"
              : def.id === currentStep
                ? "active"
                : "pending"
          const isLast = i === STEP_DEFS.length - 1
          return (
            <li key={def.id} className="relative flex gap-4 pb-6 last:pb-0">
              {!isLast ? (
                <span
                  className={`absolute left-[15px] top-9 h-[calc(100%-12px)] w-px ${
                    status === "done" ? "bg-primary/60" : "bg-border"
                  }`}
                  aria-hidden
                />
              ) : null}

              <Node status={status} index={i} />

              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  <h3
                    className={`text-sm font-semibold ${
                      status === "pending" ? "text-muted-foreground" : "text-foreground"
                    }`}
                  >
                    {def.title}
                  </h3>
                  <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {def.provider}
                  </span>
                  {status === "active" ? (
                    <span className="rounded-full border border-primary/40 px-2 py-0.5 font-mono text-[10px] text-primary">
                      live
                    </span>
                  ) : null}
                  {status === "done" ? (
                    <span className="font-mono text-[10px] text-primary">done</span>
                  ) : null}
                </div>

                {status === "active" ? (
                  <div className="mt-2 rounded-lg border border-border bg-background/60 p-2.5">
                    <p className="flex items-start gap-2 font-mono text-xs text-muted-foreground">
                      <span className="select-none text-primary/70">›</span>
                      <span className="break-words">{event?.message ?? "working…"}</span>
                    </p>
                  </div>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">{def.description}</p>
                )}
              </div>
            </li>
          )
        })}
      </ol>

      {isComplete ? (
        <div className="mt-2 flex items-center gap-2 font-mono text-xs text-primary">
          <Spinner /> Render complete — opening your demo…
        </div>
      ) : null}
    </div>
  )
}

function Node({ status, index }: { status: StepStatus; index: number }) {
  if (status === "done") {
    return (
      <span className="z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 13l4 4L19 7" />
        </svg>
      </span>
    )
  }
  if (status === "active") {
    return (
      <span className="animate-pulse-ring z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 border-primary bg-card">
        <Spinner />
      </span>
    )
  }
  return (
    <span className="z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-card font-mono text-xs text-muted-foreground">
      {index + 1}
    </span>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin text-primary" width="15" height="15" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
