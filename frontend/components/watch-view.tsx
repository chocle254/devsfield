
"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import type { RunResult } from "@/lib/types"

interface ResultPayload {
  id: string
  status: "running" | "done" | "error"
  result: RunResult | null
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

export function WatchView({ id }: { id: string }) {
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const res = await fetch(`/api/result/${id}`, { cache: "no-store" })
        const json: ResultPayload & { error?: string } = await res.json()
        if (!active) return
        if (!res.ok) {
          setError(json?.error ?? "Video not found.")
          return
        }
        if (json.status !== "done" || !json.result) {
          setError("This video isn't ready yet.")
          return
        }
        setResult(json.result)
      } catch {
        if (active) setError("Could not load this video.")
      }
    }
    load()
    return () => {
      active = false
    }
  }, [id])

  function share() {
    navigator.clipboard.writeText(window.location.href)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card p-10 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
        <Link href="/library" className="mt-4 inline-block text-sm font-medium text-primary hover:underline">
          Browse all videos
        </Link>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card p-12">
        <svg className="animate-spin text-primary" width="20" height="20" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <p className="mt-3 font-mono text-xs text-muted-foreground">Loading video…</p>
      </div>
    )
  }

  const r = result

  return (
    <div className="mx-auto max-w-3xl">
      <div className="overflow-hidden rounded-xl border border-border bg-black">
        <SequentialPlayer result={r} />
      </div>

      <div className="mt-4">
        <h1 className="text-balance text-xl font-bold tracking-tight text-foreground">{r.title}</h1>
        <p className="mt-1.5 text-pretty text-sm leading-relaxed text-muted-foreground">{r.summary}</p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/5 px-2.5 py-1 font-mono text-[11px] text-primary">
          {fmt(r.durationSec)}
        </span>
        <a
          href={`/api/download/${id}`}
          className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 sm:flex-none"
        >
          <DownloadIcon /> Download MP4
        </a>
        <button
          onClick={share}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium transition-colors hover:border-primary/40"
        >
          <LinkIcon /> {copied ? "Copied!" : "Share"}
        </button>
        <Link
          href="/library"
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          All videos
        </Link>
      </div>
    </div>
  )
}

function SequentialPlayer({ result }: { result: RunResult }) {
  const clips = (result.clipUrls ?? []).filter(Boolean)
  const hasClips = clips.length > 0
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [index, setIndex] = useState(0)

  // Whenever we advance to a new clip, load it and keep playing so the
  // segments run back-to-back with no black screen between them.
  useEffect(() => {
    if (!hasClips) return
    const v = videoRef.current
    if (!v) return
    v.load()
    const play = v.play()
    if (play && typeof play.catch === "function") play.catch(() => {})
  }, [index, hasClips])

  // Single-file fallback: play the pre-rendered final video as-is.
  if (!hasClips) {
    return (
      <video
        key={result.videoUrl}
        controls
        autoPlay
        preload="metadata"
        poster={result.posterUrl}
        className="aspect-video w-full bg-black"
      >
        <source src={result.videoUrl} type="video/mp4" />
        Your browser does not support the video tag.
      </video>
    )
  }

  const isLast = index >= clips.length - 1

  function handleEnded() {
    if (!isLast) setIndex((i) => i + 1)
  }

  return (
    <>
      <video
        ref={videoRef}
        key={clips[index]}
        controls
        autoPlay
        preload="auto"
        poster={index === 0 ? result.posterUrl : undefined}
        onEnded={handleEnded}
        className="aspect-video w-full bg-black"
      >
        <source src={clips[index]} type="video/mp4" />
        Your browser does not support the video tag.
      </video>
      {/* Warm the browser cache for the next clip to avoid a gap on switch. */}
      {!isLast ? <link rel="prefetch" as="video" href={clips[index + 1]} /> : null}
    </>
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
