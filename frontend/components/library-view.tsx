"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"

interface LibraryVideo {
  id: string
  title: string
  repoName: string | null
  githubUrl: string | null
  appUrl: string | null
  tone: string | null
  durationSec: number | null
  generatedAt: string | null
  videoUrl: string | null
  status: "complete"
}

function fmtDuration(sec: number | null): string {
  if (!sec || sec <= 0) return "—"
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

export function LibraryView() {
  const [videos, setVideos] = useState<LibraryVideo[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch("/api/library", { cache: "no-store" })
      const json = await res.json()
      if (!res.ok) throw new Error(json?.error ?? "Failed to load videos.")
      setVideos(Array.isArray(json.videos) ? json.videos : [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load videos.")
      setVideos([])
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleDelete(id: string) {
    setDeleting(id)
    try {
      const res = await fetch(`/api/library/${id}`, { method: "DELETE" })
      const json = await res.json().catch(() => null)
      if (!res.ok) throw new Error(json?.error ?? "Delete failed.")
      setVideos((prev) => (prev ? prev.filter((v) => v.id !== id) : prev))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Delete failed.")
    } finally {
      setDeleting(null)
      setConfirmId(null)
    }
  }

  const total = videos?.length ?? 0

  return (
    <div>
      {/* Stat tiles */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:gap-4">
        <StatTile label="Total videos" value={videos === null ? "…" : String(total)} />
        <StatTile label="Completed" value={videos === null ? "…" : String(total)} accent />
      </div>

      {error ? (
        <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {videos === null ? (
        <LoadingGrid />
      ) : videos.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {videos.map((v) => (
            <VideoCard
              key={v.id}
              video={v}
              deleting={deleting === v.id}
              confirming={confirmId === v.id}
              onAskDelete={() => setConfirmId(v.id)}
              onCancelDelete={() => setConfirmId(null)}
              onConfirmDelete={() => handleDelete(v.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function StatTile({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
      <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-2 text-2xl font-bold ${accent ? "text-primary" : "text-foreground"}`}>{value}</p>
    </div>
  )
}

function VideoCard({
  video,
  deleting,
  confirming,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  video: LibraryVideo
  deleting: boolean
  confirming: boolean
  onAskDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
}) {
  const [copied, setCopied] = useState(false)

  function share() {
    const url = `${window.location.origin}/watch/${video.id}`
    navigator.clipboard.writeText(url)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="flex flex-col rounded-xl border border-border bg-card p-4 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <h3 className="truncate text-sm font-semibold text-foreground">{video.title}</h3>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-primary/40 bg-primary/5 px-2 py-0.5 font-mono text-[10px] text-primary">
          Completed
        </span>
      </div>

      {video.githubUrl ? (
        <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground" title={video.githubUrl}>
          {video.githubUrl}
        </p>
      ) : (
        <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
          job {video.id.slice(0, 8)}
        </p>
      )}

      <div className="mt-3 flex items-center gap-3 font-mono text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <ClockIcon /> {fmtDuration(video.durationSec)}
        </span>
        <span className="inline-flex items-center gap-1">
          <CalendarIcon /> {fmtDate(video.generatedAt)}
        </span>
      </div>

      {/* Actions */}
      {confirming ? (
        <div className="mt-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
          <p className="text-xs text-foreground">
            Permanently delete this video and all its files from Backblaze B2? This can&apos;t be undone.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              onClick={onConfirmDelete}
              disabled={deleting}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-destructive px-3 py-2 text-xs font-semibold text-destructive-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {deleting ? "Deleting…" : "Delete"}
            </button>
            <button
              onClick={onCancelDelete}
              disabled={deleting}
              className="inline-flex flex-1 items-center justify-center rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium transition-colors hover:border-primary/40 disabled:opacity-60"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Link
            href={`/watch/${video.id}`}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            <PlayIcon /> Watch
          </Link>
          <a
            href={`/api/download/${video.id}`}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium transition-colors hover:border-primary/40"
          >
            <DownloadIcon /> Download
          </a>
          <button
            onClick={share}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium transition-colors hover:border-primary/40"
          >
            <LinkIcon /> {copied ? "Copied!" : "Share"}
          </button>
          <button
            onClick={onAskDelete}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium text-destructive transition-colors hover:border-destructive/40"
          >
            <TrashIcon /> Delete
          </button>
        </div>
      )}
    </div>
  )
}

function LoadingGrid() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="rounded-xl border border-border bg-card p-5">
          <div className="h-4 w-2/3 animate-pulse rounded bg-input" />
          <div className="mt-3 h-3 w-full animate-pulse rounded bg-input" />
          <div className="mt-4 h-8 w-full animate-pulse rounded bg-input" />
        </div>
      ))}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-border bg-card p-10 text-center">
      <p className="text-sm font-medium text-foreground">No videos yet</p>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Generate your first demo video and it will show up here.
      </p>
      <Link
        href="/#start"
        className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
      >
        New demo
      </Link>
    </div>
  )
}

function PlayIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
    </svg>
  )
}

function LinkIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    </svg>
  )
}

function ClockIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  )
}

function CalendarIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  )
}
