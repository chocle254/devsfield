"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import type { Asset, RunResult } from "@/lib/types"
import { SceneTimeline } from "@/components/scene-timeline"
import { EditChat } from "@/components/edit-chat"

interface ResultPayload {
  id: string
  status: "running" | "done" | "error"
  repoUrl: string
  appUrl: string
  result: RunResult | null
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

export function ResultView({ id }: { id: string }) {
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let active = true
    async function load() {
      const res = await fetch(`/api/result/${id}`, { cache: "no-store" })
      if (!res.ok) {
        if (active) setError("Run not found.")
        return
      }
      const json: ResultPayload = await res.json()
      if (!active) return
      if (json.status !== "done" || !json.result) {
        setTimeout(load, 800)
        return
      }
      setResult(json.result)
    }
    load()
    return () => {
      active = false
    }
  }, [id])

  // Highlight the most recently edited scene on the timeline.
  const activeSceneId = useMemo(() => {
    const patches = (result?.edits ?? []).filter((e) => e.role === "assistant" && e.patch?.sceneId)
    return patches.length ? patches[patches.length - 1].patch?.sceneId ?? null : null
  }, [result?.edits])

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
      {/* Player + actions — mobile: 1st, desktop: top-left */}
      <div className="lg:col-span-3 lg:col-start-1 lg:row-start-1">
        <div className="relative overflow-hidden rounded-xl border border-border bg-black">
          {/* No crossOrigin: the video is never drawn to a canvas, and setting
              it would force a CORS check that a private presigned B2 URL
              (without bucket CORS rules) would fail — blocking playback. */}
          <video
            key={r.videoUrl}
            controls
            poster={r.posterUrl}
            preload="metadata"
            className="aspect-video w-full bg-black"
          >
            <source src={r.videoUrl} type="video/mp4" />
            Your browser does not support the video tag.
          </video>
          {r.presenter?.enabled ? <PresenterCam presenter={r.presenter} /> : null}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/5 px-2.5 py-1 font-mono text-[11px] text-primary">
            v{r.version} · {fmt(r.durationSec)}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 font-mono text-[11px] text-muted-foreground">
            {r.format === "pitch_demo" ? "pitch + demo" : "demo"}
          </span>
          {/* Same-origin proxy: browsers ignore `download` on cross-origin
              (B2) links, so we stream the file through our own route with a
              Content-Disposition attachment header instead. */}
          <a
            href={`/api/download/${id}`}
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
      </div>

      {/* Edit chat — mobile: 2nd (right under player), desktop: full-height right column */}
      <div className="h-[460px] sm:h-[520px] lg:col-span-2 lg:col-start-4 lg:row-start-1 lg:row-span-2 lg:h-auto">
        <EditChat id={id} result={r} onResult={setResult} />
      </div>

      {/* Timeline — desktop: under player */}
      <div className="lg:col-span-3 lg:col-start-1 lg:row-start-2">
        <SceneTimeline scenes={r.scenes} durationSec={r.durationSec} activeSceneId={activeSceneId} />
      </div>

      {/* Details — desktop: row 3 left */}
      <div className="rounded-xl border border-border bg-card p-4 sm:p-5 lg:col-span-3 lg:col-start-1 lg:row-start-3">
        <h2 className="text-sm font-semibold">{r.title}</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{r.summary}</p>
        <div className="mt-4">
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            Narration script
          </p>
          <p className="mt-2 max-h-44 overflow-y-auto whitespace-pre-line text-xs leading-relaxed text-muted-foreground/90">
            {r.scenes.map((s) => s.script).join("\n\n")}
          </p>
        </div>
      </div>

      {/* Provenance — desktop: row 3 right */}
      <div className="lg:col-span-2 lg:col-start-4 lg:row-start-3">
        <ProvenanceCard result={r} id={id} />
      </div>
    </div>
  )
}

function PresenterCam({ presenter }: { presenter: NonNullable<RunResult["presenter"]> }) {
  return (
    <div className="pointer-events-none absolute bottom-3 right-3 flex flex-col items-center gap-1">
      <div className="presenter-bob relative h-20 w-20 overflow-hidden rounded-full border-2 border-primary/80 bg-card shadow-lg sm:h-24 sm:w-24">
        <span className="presenter-ring absolute inset-0 rounded-full" aria-hidden />
        {presenter.photoUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={presenter.photoUrl || "/placeholder.svg"}
            alt={presenter.name ? `${presenter.name}, presenting` : "Presenter"}
            className="h-full w-full object-cover"
          />
        ) : (
          <span className="flex h-full w-full items-center justify-center font-mono text-xs text-muted-foreground">
            {(presenter.name ?? "You").slice(0, 2).toUpperCase()}
          </span>
        )}
      </div>
      {presenter.name ? (
        <span className="rounded bg-background/80 px-1.5 py-0.5 font-mono text-[10px] text-foreground backdrop-blur">
          {presenter.name}
        </span>
      ) : null}
    </div>
  )
}

function ProvenanceCard({ result, id }: { result: RunResult; id: string }) {
  const r = result
  return (
    <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Asset provenance</h2>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 px-2 py-0.5 font-mono text-[10px] text-primary">
          <B2Icon /> Backblaze B2
        </span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
        Every artifact is uploaded to Backblaze B2 with a SHA-256 fingerprint. Edits only re-hash the
        assets that actually changed.
      </p>

      <ul className="mt-4 space-y-2">
        {r.assets.map((a) => (
          <AssetRow key={a.key} asset={a} />
        ))}
      </ul>

      <div className="mt-4 rounded-lg border border-border bg-background/60 p-3">
        <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Bucket</p>
        <p className="mt-1 break-all font-mono text-xs text-foreground">
          b2://{r.assets[0]?.b2Key.split("/")[0] ?? "devfields"}/runs/{id}/
        </p>
      </div>
    </div>
  )
}

function AssetRow({ asset }: { asset: Asset }) {
  return (
    <li className="flex items-center gap-3 rounded-lg border border-border bg-background/40 p-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-input text-muted-foreground">
        <KindIcon kind={asset.kind} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium">{asset.label}</p>
        <p className="truncate font-mono text-[11px] text-muted-foreground">{asset.b2Key}</p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-0.5">
        <span className="font-mono text-[11px] text-muted-foreground">{asset.size}</span>
        <span className="font-mono text-[10px] text-primary/80" title="SHA-256">
          {asset.hash}
        </span>
      </div>
    </li>
  )
}

function KindIcon({ kind }: { kind: Asset["kind"] }) {
  const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const }
  if (kind === "video") return <svg {...common}><polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
  if (kind === "audio") return <svg {...common}><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></svg>
  if (kind === "image") return <svg {...common}><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="M21 15l-5-5L5 21" /></svg>
  if (kind === "json") return <svg {...common}><path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1M16 3h1a2 2 0 0 1 2 2v5a2 2 0 0 0 2 2 2 2 0 0 0-2 2v5a2 2 0 0 1-2 2h-1" /></svg>
  return <svg {...common}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M16 13H8M16 17H8" /></svg>
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

function B2Icon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L2 7v10l10 5 10-5V7L12 2zm0 2.2L19.5 8 12 11.8 4.5 8 12 4.2z" />
    </svg>
  )
}
