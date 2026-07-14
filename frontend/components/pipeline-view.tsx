"use client"

import Image from "next/image"
import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { BACKEND_STEPS } from "@/lib/steps"

interface NavigationSnapshot {
  id: string
  url: string
  title: string
  captured_at: string
  image_url: string
}

interface StreamPayload {
  job_id?: string
  status: "queued" | "in_progress" | "complete" | "failed"
  current_step?: string | null
  steps_completed?: string[]
  message?: string
  error?: string | null
  snapshots?: NavigationSnapshot[]
  video_url?: string
}

export function PipelineView({ id }: { id: string }) {
  const router = useRouter()
  const [data, setData] = useState<StreamPayload | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)
  // Bumping this re-runs the streaming effect with a fresh connection, which
  // is how we resume watching progress after a retry.
  const [retryNonce, setRetryNonce] = useState(0)
  const redirected = useRef(false)
  const latestSnapshotId = useRef<string | null>(null)

  async function handleRetry() {
    setRetrying(true)
    setRetryError(null)
    try {
      const res = await fetch(`/api/retry/${id}`, { method: "POST" })
      const payload = await res.json().catch(() => null)
      if (!res.ok) {
        setRetryError(payload?.error ?? "Could not retry this run. Please try again.")
        return
      }
      // Resume: clear the failed state and reconnect to the stream. The backend
      // continues from the step that broke, reusing completed work.
      redirected.current = false
      setData((prev) => (prev ? { ...prev, status: "in_progress", error: null } : prev))
      setRetryNonce((n) => n + 1)
    } catch {
      setRetryError("Could not reach the server. Please try again.")
    } finally {
      setRetrying(false)
    }
  }

  useEffect(() => {
    let es: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    // Once the run reaches a terminal state (done / failed / not found) we stop
    // reconnecting. While it is still in progress we always try to reconnect,
    // because the job keeps running on the server even if this tab is
    // backgrounded, throttled, or the connection is dropped.
    let stopped = false

    const clearReconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    }

    const connect = () => {
      if (stopped) return
      es?.close()
      es = new EventSource(`/api/stream/${id}`)

      es.onmessage = (e) => {
        const raw = JSON.parse(e.data)
        if (raw.error === "not_found" || raw.error === "Job not found") {
          setNotFound(true)
          stopped = true
          es?.close()
          return
        }
        const latestSnapshot = raw.snapshots?.at(-1) as NavigationSnapshot | undefined
        if (latestSnapshot && latestSnapshot.id !== latestSnapshotId.current) {
          latestSnapshotId.current = latestSnapshot.id
          setSelectedSnapshotId(latestSnapshot.id)
        }
        setData(raw)
        if (raw.status === "complete" && !redirected.current) {
          redirected.current = true
          stopped = true
          es?.close()
          setTimeout(() => router.push(`/result/${id}`), 900)
        }
        if (raw.status === "failed") {
          stopped = true
          es?.close()
        }
      }

      es.onerror = () => {
        // The tab was likely backgrounded/suspended or the network blipped.
        // Reconnect (unless we're already done) to resync with the server.
        es?.close()
        if (stopped) return
        clearReconnect()
        reconnectTimer = setTimeout(connect, 2000)
      }
    }

    const handleVisibility = () => {
      if (document.visibilityState === "visible" && !stopped) {
        // Reconnect immediately when the user returns to the tab instead of
        // waiting for the backoff timer, so progress catches up right away.
        clearReconnect()
        connect()
      }
    }

    connect()
    document.addEventListener("visibilitychange", handleVisibility)

    return () => {
      stopped = true
      clearReconnect()
      document.removeEventListener("visibilitychange", handleVisibility)
      es?.close()
    }
  }, [id, router, retryNonce])

  if (notFound) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 text-center shadow-sm">
        <p className="text-sm text-muted-foreground">This run could not be found. It may have expired.</p>
      </div>
    )
  }

  const status = data?.status ?? "queued"
  const isDone = status === "complete"
  const isError = status === "failed"

  const completed = new Set(
    (data?.steps_completed ?? []).filter((sid) => BACKEND_STEPS.some((s) => s.id === sid)),
  )
  const doneCount = BACKEND_STEPS.filter((s) => completed.has(s.id)).length
  const currentIndex = BACKEND_STEPS.findIndex((s) => s.id === data?.current_step)
  const total = BACKEND_STEPS.length

  // Real progress: completed steps, plus half-credit for the step currently
  // running so the bar advances as soon as a new step starts.
  const progress = isDone
    ? 100
    : Math.min(96, Math.round(((doneCount + (currentIndex >= 0 ? 0.5 : 0)) / total) * 100))

  // Primary status line, matching the backend's real activity.
  const statusLabel = isError
    ? "Generation failed"
    : isDone
      ? "Done — opening your demo…"
      : currentIndex >= 0
        ? BACKEND_STEPS[currentIndex].label
        : doneCount > 0 && doneCount < total
          ? BACKEND_STEPS[doneCount].label
          : data?.message ?? "Preparing pipeline…"

  const snapshots = data?.snapshots ?? []
  const selectedSnapshot =
    snapshots.find((snapshot) => snapshot.id === selectedSnapshotId) ?? snapshots.at(-1)
  const isBrowsing = data?.current_step === "app_browser"

  return (
    <div className="space-y-5">
      {/* Live progress card */}
      <section
        className={`rounded-xl border bg-card p-5 shadow-sm ${
          isError ? "border-destructive/40" : "border-border"
        }`}
        aria-live="polite"
      >
        <div className="flex items-center gap-2.5">
          {isError ? (
            <AlertIcon />
          ) : isDone ? (
            <CheckCircleIcon />
          ) : (
            <Spinner />
          )}
          <p className={`text-sm font-medium ${isError ? "text-destructive" : "text-foreground"}`}>
            {statusLabel}
          </p>
          {!isError && !isDone ? (
            <span className="ml-auto text-sm font-semibold tabular-nums text-primary">{progress}%</span>
          ) : null}
        </div>

        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className={`relative h-full rounded-full transition-all duration-700 ease-out ${
              isError ? "bg-destructive" : "bg-primary"
            } ${!isError && !isDone ? "progress-shimmer" : ""}`}
            style={{ width: `${isError ? 100 : progress}%` }}
          />
        </div>

        <p className="mt-3 text-xs text-muted-foreground">
          {isError
            ? (data?.error ?? "Something went wrong while generating your video.")
            : "Do not close this page. Generation continues on the server."}
        </p>

        {isError ? (
          <div className="mt-4 border-t border-border pt-4">
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleRetry}
                disabled={retrying}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              >
                {retrying ? <Spinner /> : <RetryIcon />}
                {retrying ? "Resuming…" : "Retry from failed step"}
              </button>
              <p className="text-xs text-muted-foreground">
                {doneCount > 0
                  ? `Keeps your ${doneCount} completed ${doneCount === 1 ? "step" : "steps"} and resumes from where it stopped.`
                  : "Resumes the run without starting over."}
              </p>
            </div>
            {retryError ? (
              <p className="mt-2 text-xs text-destructive">{retryError}</p>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* Snapshots — what the AI is seeing as it navigates the app */}
      {isBrowsing || snapshots.length > 0 ? (
        <NavigationViewer
          runId={id}
          snapshots={snapshots}
          selectedSnapshot={selectedSnapshot}
          onSelect={setSelectedSnapshotId}
          isLive={isBrowsing}
        />
      ) : null}

      {/* Step checklist — the real pipeline stages */}
      <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-foreground">Pipeline</h2>
        <ol className="mt-3 space-y-2.5">
          {BACKEND_STEPS.map((step) => {
            const done = completed.has(step.id)
            const active = step.id === data?.current_step
            const errored = isError && active
            return (
              <li key={step.id} className="flex items-center gap-3">
                <StepNode done={done} active={active} errored={errored} />
                <span
                  className={`text-sm ${
                    done
                      ? "text-foreground"
                      : active
                        ? "font-medium text-foreground"
                        : "text-muted-foreground"
                  }`}
                >
                  {step.label}
                </span>
                {active && !isError ? (
                  <span className="ml-auto text-xs font-medium text-primary">running</span>
                ) : done ? (
                  <span className="ml-auto text-xs text-success">done</span>
                ) : null}
              </li>
            )
          })}
        </ol>
      </section>
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
  const hostname = selectedSnapshot ? getHostname(selectedSnapshot.url) : "Waiting for the browser"

  return (
    <section
      className="overflow-hidden rounded-xl border border-border bg-card shadow-sm"
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
              Live navigation snapshots
            </h2>
          </div>
          <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{hostname}</p>
        </div>
        <span className="shrink-0 rounded-full bg-accent px-2.5 py-1 text-[11px] font-medium text-accent-foreground">
          {snapshots.length} {snapshots.length === 1 ? "page" : "pages"}
        </span>
      </div>

      <div className="p-3 sm:p-4">
        <div className="relative aspect-video overflow-hidden rounded-lg border border-border bg-secondary">
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
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent">
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
              <p className="truncate text-sm font-medium text-foreground">{selectedSnapshot.title}</p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                {selectedSnapshot.url}
              </p>
            </div>
            <span className="shrink-0 text-[11px] font-medium text-success">loaded</span>
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
                  className={`relative aspect-video w-28 shrink-0 overflow-hidden rounded-md border bg-secondary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
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
                  <span className="absolute bottom-1 left-1 rounded bg-card/90 px-1.5 py-0.5 font-mono text-[9px] text-foreground">
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

function StepNode({ done, active, errored }: { done: boolean; active: boolean; errored: boolean }) {
  if (errored) {
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-destructive text-destructive-foreground">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </span>
    )
  }
  if (done) {
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 13l4 4L19 7" />
        </svg>
      </span>
    )
  }
  if (active) {
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-primary bg-card">
        <Spinner />
      </span>
    )
  }
  return (
    <span className="h-6 w-6 shrink-0 rounded-full border border-border bg-secondary" aria-hidden />
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

function CheckCircleIcon() {
  return (
    <svg className="text-success" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </svg>
  )
}

function RetryIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v5h-5" />
    </svg>
  )
}

function AlertIcon() {
  return (
    <svg className="text-destructive" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4M12 16h.01" />
    </svg>
  )
}
