"use client"

import Image from "next/image"
import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { STEP_DEFS, STEP_DEF_BY_ID } from "@/lib/steps"
import type { StepState } from "@/lib/types"

interface NavigationSnapshot {
  id: string
  url: string
  title: string
  captured_at: string
  image_url: string
}

interface StreamPayload {
  // Backend sends "complete" | "failed" | "in_progress" | "queued".
  // We normalise to the frontend vocabulary immediately after parsing.
  id: string
  job_id?: string
  status: "running" | "done" | "error" | "complete" | "in_progress" | "queued" | "failed"
  steps: StepState[]
  steps_completed?: string[]
  current_step?: string
  message?: string
  activity?: string
  activity_seq?: number
  activity_updated_at?: string
  snapshots?: NavigationSnapshot[]
  repoUrl: string
  appUrl: string
}

export function PipelineView({ id }: { id: string }) {
  const router = useRouter()
  const [data, setData] = useState<StreamPayload | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null)
  const [reconnecting, setReconnecting] = useState(false)
  const [elapsedSec, setElapsedSec] = useState(0)
  const [lastUpdateAt, setLastUpdateAt] = useState<number>(() => Date.now())
  const [now, setNow] = useState<number>(() => Date.now())
  const redirected = useRef(false)
  const latestSnapshotId = useRef<string | null>(null)
  const startedAt = useRef<number>(Date.now())

  // Tick every second so the elapsed timer and quiet-period notice stay live.
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAt.current) / 1000))
      setNow(Date.now())
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    let es: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let closedForGood = false

    const connect = () => {
      es = new EventSource(`/api/stream/${id}`)
      es.onopen = () => setReconnecting(false)
      es.onmessage = (e) => {
        setReconnecting(false)
        setLastUpdateAt(Date.now())
        const raw = JSON.parse(e.data)
        if (raw.error === "not_found" || raw.error === "Job not found") {
          setNotFound(true)
          closedForGood = true
          es?.close()
          return
        }
        // Normalise backend status vocabulary → frontend vocabulary
        if (raw.status === "complete") raw.status = "done"
        if (raw.status === "failed") raw.status = "error"
        if (raw.status === "in_progress" || raw.status === "queued") raw.status = "running"
        const latestSnapshot = raw.snapshots?.at(-1) as NavigationSnapshot | undefined
        if (latestSnapshot && latestSnapshot.id !== latestSnapshotId.current) {
          latestSnapshotId.current = latestSnapshot.id
          setSelectedSnapshotId(latestSnapshot.id)
        }
        setData(raw)
        if (raw.status === "done" && !redirected.current) {
          redirected.current = true
          closedForGood = true
          es?.close()
          setTimeout(() => router.push(`/result/${id}`), 900)
        }
        if (raw.status === "error") {
          closedForGood = true
          es?.close()
        }
      }
      es.onerror = () => {
        es?.close()
        if (closedForGood || redirected.current) return
        // Transient network hiccup — show it and retry instead of freezing.
        setReconnecting(true)
        retryTimer = setTimeout(connect, 2500)
      }
    }

    connect()
    return () => {
      closedForGood = true
      if (retryTimer) clearTimeout(retryTimer)
      es?.close()
    }
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
  const snapshots = data?.snapshots ?? []
  const selectedSnapshot =
    snapshots.find((snapshot) => snapshot.id === selectedSnapshotId) ?? snapshots.at(-1)
  const isBrowsing = data?.current_step === "app_browser"
  const isRunning = !isDone && data?.status !== "error" && !notFound
  // Quiet period: no fresh stream data for a while — reassure the user.
  const quietForSec = Math.max(0, Math.floor((now - lastUpdateAt) / 1000))
  const activityText =
    data?.activity ?? data?.message ?? "Starting your run"

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

      {isBrowsing || snapshots.length > 0 ? (
        <NavigationViewer
          runId={id}
          snapshots={snapshots}
          selectedSnapshot={selectedSnapshot}
          onSelect={setSelectedSnapshotId}
          isLive={isBrowsing}
        />
      ) : null}

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

function NavigationViewer({
  runId,
  snapshots,
  selectedSnapshot,
  onSelect,
  isLive,
}: {
  runId: string
  snapshots: NavigationSnapshot[]
  selectedSnapshot?: NavigationSnapshot
  onSelect: (id: string) => void
  isLive: boolean
}) {
  const hostname = selectedSnapshot
    ? getHostname(selectedSnapshot.url)
    : "Waiting for the browser"

  return (
    <section
      className="mb-8 overflow-hidden rounded-xl border border-border bg-card"
      aria-labelledby="navigation-viewer-title"
    >
      <div className="flex items-center justify-between gap-3 border-b border-border p-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 shrink-0 rounded-full bg-primary ${isLive ? "animate-pulse" : ""}`}
              aria-hidden="true"
            />
            <h2 id="navigation-viewer-title" className="text-sm font-semibold text-foreground">
              AI is navigating
            </h2>
          </div>
          <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
            {hostname}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-primary/40 px-2.5 py-1 font-mono text-[10px] text-primary">
          {snapshots.length} {snapshots.length === 1 ? "page" : "pages"}
        </span>
      </div>

      <div className="p-3 sm:p-4">
        <div className="relative aspect-video overflow-hidden rounded-lg border border-border bg-background">
          {selectedSnapshot ? (
            <Image
              key={selectedSnapshot.id}
              src={`/api/snapshot/${encodeURIComponent(runId)}/${encodeURIComponent(selectedSnapshot.id)}`}
              alt={`AI browser view of ${selectedSnapshot.title} at ${hostname}`}
              fill
              unoptimized
              sizes="(max-width: 640px) 100vw, 720px"
              className="object-contain"
              priority
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
              <span className="flex h-10 w-10 items-center justify-center rounded-full border border-primary/40 bg-primary/10">
                <Spinner />
              </span>
              <div>
                <p className="text-sm font-medium text-foreground">Opening your app</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  The first loaded page will appear here.
                </p>
              </div>
            </div>
          )}
        </div>

        {selectedSnapshot ? (
          <div className="mt-3 flex items-start justify-between gap-3" aria-live="polite">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">
                {selectedSnapshot.title}
              </p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                {selectedSnapshot.url}
              </p>
            </div>
            <span className="shrink-0 font-mono text-[10px] text-primary">
              loaded
            </span>
          </div>
        ) : null}

        {snapshots.length > 1 ? (
          <div className="mt-4 flex gap-2 overflow-x-auto pb-1" aria-label="Loaded page history">
            {snapshots.map((snapshot, index) => {
              const selected = snapshot.id === selectedSnapshot?.id
              return (
                <button
                  key={snapshot.id}
                  type="button"
                  onClick={() => onSelect(snapshot.id)}
                  aria-pressed={selected}
                  aria-label={`View loaded page ${index + 1}: ${snapshot.title}`}
                  className={`relative aspect-video w-28 shrink-0 overflow-hidden rounded-md border bg-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                    selected ? "border-primary" : "border-border hover:border-primary/50"
                  }`}
                >
                  <Image
                    src={`/api/snapshot/${encodeURIComponent(runId)}/${encodeURIComponent(snapshot.id)}`}
                    alt=""
                    fill
                    unoptimized
                    sizes="112px"
                    className="object-cover"
                  />
                  <span className="absolute bottom-1 left-1 rounded bg-background/90 px-1.5 py-0.5 font-mono text-[9px] text-foreground">
                    {index + 1}
                  </span>
                </button>
              )
            })}
          </div>
        ) : null}
      </div>
    </section>
  )
}

function getHostname(url: string) {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
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
