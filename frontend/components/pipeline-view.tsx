"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { STEP_DEFS, STEP_DEF_BY_ID } from "@/lib/steps"
import type { StepState } from "@/lib/types"

interface StreamPayload {
  id: string
  status: "running" | "done" | "error"
  steps: StepState[]
  repoUrl: string
  appUrl: string
}

export function PipelineView({ id }: { id: string }) {
  const router = useRouter()
  const [data, setData] = useState<StreamPayload | null>(null)
  const [notFound, setNotFound] = useState(false)
  const redirected = useRef(false)

  useEffect(() => {
    const es = new EventSource(`/api/stream/${id}`)
    es.onmessage = (e) => {
      const payload = JSON.parse(e.data)
      if (payload.error === "not_found") {
        setNotFound(true)
        es.close()
        return
      }
      setData(payload)
      if (payload.status === "done" && !redirected.current) {
        redirected.current = true
        es.close()
        setTimeout(() => router.push(`/result/${id}`), 900)
      }
    }
    es.onerror = () => es.close()
    return () => es.close()
  }, [id, router])

  if (notFound) {
    return (
      <div className="rounded-xl border border-border bg-card p-8 text-center">
        <p className="text-sm text-muted-foreground">This run could not be found. It may have expired.</p>
      </div>
    )
  }

  const steps = data?.steps ?? STEP_DEFS.map((d) => ({ id: d.id, status: "pending" as const, logs: [], mode: "simulated" as const }))
  const doneCount = steps.filter((s) => s.status === "done").length
  const progress = Math.round((doneCount / Math.max(steps.length, 1)) * 100)
  const isDone = data?.status === "done"

  return (
    <div className="w-full">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-muted-foreground">
            {data?.repoUrl ?? "resolving repository…"}
          </p>
        </div>
        <span className="shrink-0 font-mono text-xs text-primary">{progress}%</span>
      </div>

      <div className="mb-8 h-1 w-full overflow-hidden rounded-full bg-input">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
          style={{ width: `${isDone ? 100 : progress}%` }}
        />
      </div>

      <ol className="relative">
        {steps.map((state, i) => {
          const def = STEP_DEF_BY_ID[state.id] ?? {
            id: state.id,
            title: state.id,
            description: "",
            provider: "Devfields" as const,
            duration: 0,
          }
          const isLast = i === steps.length - 1
          return (
            <li key={def.id} className="relative flex gap-4 pb-6 last:pb-0">
              {/* connector */}
              {!isLast ? (
                <span
                  className={`absolute left-[15px] top-9 h-[calc(100%-12px)] w-px ${
                    state.status === "done" ? "bg-primary/60" : "bg-border"
                  }`}
                  aria-hidden
                />
              ) : null}

              <Node status={state.status} index={i} />

              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  <h3
                    className={`text-sm font-semibold ${
                      state.status === "pending" ? "text-muted-foreground" : "text-foreground"
                    }`}
                  >
                    {def.title}
                  </h3>
                  <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {def.provider}
                  </span>
                  {state.status === "active" ? (
                    <ModeTag mode={state.mode} />
                  ) : null}
                  {state.status === "done" ? (
                    <span className="font-mono text-[10px] text-primary">done</span>
                  ) : null}
                </div>

                {state.status === "active" || state.status === "done" ? (
                  <div className="mt-2 rounded-lg border border-border bg-background/60 p-2.5">
                    {state.logs.length === 0 ? (
                      <p className="font-mono text-xs text-muted-foreground">initializing…</p>
                    ) : (
                      <ul className="space-y-1">
                        {state.logs.map((line, li) => (
                          <li key={li} className="flex items-start gap-2 font-mono text-xs text-muted-foreground">
                            <span className="select-none text-primary/70">›</span>
                            <span className="break-words">{line}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">{def.description}</p>
                )}
              </div>
            </li>
          )
        })}
      </ol>

      {isDone ? (
        <div className="mt-2 flex items-center gap-2 font-mono text-xs text-primary">
          <Spinner /> Render complete — opening your demo…
        </div>
      ) : null}
    </div>
  )
}

function Node({ status, index }: { status: StepState["status"]; index: number }) {
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

function ModeTag({ mode }: { mode: "real" | "simulated" }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 font-mono text-[10px] ${
        mode === "real"
          ? "border border-primary/40 text-primary"
          : "border border-border text-muted-foreground"
      }`}
    >
      {mode === "real" ? "live api" : "simulated"}
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
