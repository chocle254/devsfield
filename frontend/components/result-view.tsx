"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import type { RunResult, Segment } from "@/lib/types"

interface ResultPayload {
  id: string
  status: "queued" | "in_progress" | "complete" | "failed"
  result: RunResult | null
}

export function ResultView({ id }: { id: string }) {
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>

    async function load() {
      try {
        const res = await fetch(`/api/result/${id}`, { cache: "no-store" })
        if (!res.ok) {
          if (active) setError(res.status === 404 ? "Run not found." : "Could not load this run.")
          return
        }
        const json: ResultPayload = await res.json()
        if (!active) return
        if (json.status === "failed") {
          setError("This run failed during generation.")
          return
        }
        if (json.status !== "complete" || !json.result) {
          timer = setTimeout(load, 1000)
          return
        }
        setResult(json.result)
      } catch {
        if (active) timer = setTimeout(load, 1500)
      }
    }

    load()
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [id])

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card p-8 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
        <Link href="/" className="mt-4 inline-block text-sm font-medium text-primary hover:underline">
          ← Start a new run
        </Link>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card p-12">
        <Spinner />
        <p className="mt-3 font-mono text-xs text-muted-foreground">Loading your demo…</p>
      </div>
    )
  }

  const r = result

  function copyLink() {
    navigator.clipboard.writeText(window.location.href)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-5 lg:gap-6">
      {/* Player + actions */}
      <div className="lg:col-span-3">
        <div className="relative overflow-hidden rounded-xl border border-border bg-black">
          <video
            key={r.videoUrl}
            controls
            poster="/demo-poster.png"
            preload="metadata"
            crossOrigin="anonymous"
            className="aspect-video w-full bg-black"
          >
            <source src={r.videoUrl} type="video/mp4" />
            Your browser does not support the video tag.
          </video>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <a
            href={r.videoUrl}
            download
            className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 sm:flex-none"
          >
            <DownloadIcon /> Download MP4
          </a>
          <button
            onClick={copyLink}
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium transition-colors hover:border-primary/40"
          >
            <LinkIcon /> {copied ? "Copied!" : "Share"}
          </button>
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            New run
          </Link>
        </div>

        {/* Models used */}
        {r.modelsUsed ? (
          <div className="mt-5 rounded-xl border border-border bg-card p-4 sm:p-5">
            <h2 className="text-sm font-semibold">Models used</h2>
            <ul className="mt-3 space-y-2">
              {Object.entries(r.modelsUsed).map(([role, model]) => (
                <li key={role} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-background/40 px-3 py-2">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{role}</span>
                  <span className="font-mono text-xs text-foreground">{model}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {/* Provenance + segments */}
      <div className="flex flex-col gap-5 lg:col-span-2">
        <ProvenanceCard result={r} id={id} />
        <SegmentsCard segments={r.segments ?? []} />
      </div>
    </div>
  )
}

function ProvenanceCard({ result, id }: { result: RunResult; id: string }) {
  const r = result
  return (
    <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Provenance</h2>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 px-2 py-0.5 font-mono text-[10px] text-primary">
          <B2Icon /> Backblaze B2
        </span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
        Every artifact is uploaded to Backblaze B2 with a SHA-256 fingerprint recorded in the manifest.
      </p>

      <dl className="mt-4 space-y-3">
        {r.sha256 ? (
          <div>
            <dt className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">SHA-256</dt>
            <dd className="mt-1 break-all font-mono text-xs text-foreground">{r.sha256}</dd>
          </div>
        ) : null}
        {r.generatedAt ? (
          <div>
            <dt className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Generated</dt>
            <dd className="mt-1 font-mono text-xs text-foreground">
              {new Date(r.generatedAt).toLocaleString()}
            </dd>
          </div>
        ) : null}
        <div>
          <dt className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Job</dt>
          <dd className="mt-1 break-all font-mono text-xs text-foreground">jobs/{id}/</dd>
        </div>
      </dl>

      <div className="mt-4 flex flex-wrap gap-2">
        {r.manifestUrl ? (
          <a
            href={r.manifestUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background/40 px-3 py-1.5 font-mono text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          >
            manifest.json
          </a>
        ) : null}
        {r.segmentsUrl ? (
          <a
            href={r.segmentsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background/40 px-3 py-1.5 font-mono text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          >
            segments_manifest.json
          </a>
        ) : null}
      </div>
    </div>
  )
}

function SegmentsCard({ segments }: { segments: Segment[] }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Segments</h2>
        <span className="font-mono text-[11px] text-muted-foreground">{segments.length} stored</span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
        Each segment&apos;s clip and voiceover are stored individually — the foundation for regenerating
        one part without re-running the whole pipeline.
      </p>

      {segments.length === 0 ? (
        <p className="mt-4 font-mono text-xs text-muted-foreground">No segment breakdown available.</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {segments.map((seg, i) => (
            <li key={seg.segment_id} className="rounded-lg border border-border bg-background/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-input font-mono text-[11px] text-muted-foreground">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground">
                  {seg.segment_id}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <a
                  href={seg.clip_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <VideoIcon /> clip.mp4
                </a>
                <a
                  href={seg.voice_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <AudioIcon /> voice.mp3
                </a>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin text-primary" width="20" height="20" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
    </svg>
  )
}

function LinkIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
    </svg>
  )
}

function VideoIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="23 7 16 12 23 17 23 7" />
      <rect x="1" y="5" width="15" height="14" rx="2" />
    </svg>
  )
}

function AudioIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18V5l12-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="18" cy="16" r="3" />
    </svg>
  )
}

function B2Icon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L2 7v10l10 5 10-5V7L12 2zm0 2.2L19.5 8 12 11.8 4.5 8 12 4.2z" />
    </svg>
  )
}
