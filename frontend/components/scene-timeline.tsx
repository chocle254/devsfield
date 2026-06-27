"use client"

import type { Scene } from "@/lib/types"

function fmt(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

export function SceneTimeline({
  scenes,
  durationSec,
  activeSceneId,
}: {
  scenes: Scene[]
  durationSec: number
  activeSceneId?: string | null
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Timeline</h2>
        <span className="font-mono text-[11px] text-muted-foreground">
          {scenes.length} scenes · {fmt(durationSec)}
        </span>
      </div>

      {/* Proportional segment bar */}
      <div className="mt-3 flex h-2.5 w-full gap-1 overflow-hidden rounded-full">
        {scenes.map((s) => {
          const pct = ((s.endSec - s.startSec) / durationSec) * 100
          const isActive = s.id === activeSceneId
          return (
            <div
              key={s.id}
              style={{ width: `${Math.max(pct, 4)}%` }}
              className={[
                "h-full rounded-full transition-colors",
                s.status === "rendering"
                  ? "animate-pulse bg-primary"
                  : isActive || s.status === "edited"
                    ? "bg-primary"
                    : "bg-input",
              ].join(" ")}
              title={s.title}
            />
          )
        })}
      </div>

      {/* Scene chips */}
      <ul className="mt-3 flex flex-col gap-1.5">
        {scenes.map((s) => {
          const isActive = s.id === activeSceneId
          return (
            <li
              key={s.id}
              className={[
                "flex items-center gap-3 rounded-lg border px-3 py-2 transition-colors",
                isActive || s.status === "edited"
                  ? "border-primary/40 bg-primary/5"
                  : "border-border bg-background/40",
              ].join(" ")}
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-input font-mono text-[11px] text-muted-foreground">
                {s.index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium">{s.title}</span>
              {s.status === "rendering" ? (
                <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-primary">
                  <Dot /> re-rendering
                </span>
              ) : s.status === "edited" ? (
                <span className="rounded-full border border-primary/40 px-2 py-0.5 font-mono text-[10px] text-primary">
                  edited
                </span>
              ) : null}
              <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                {fmt(s.startSec)}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Dot() {
  return <span className="inline-block h-1.5 w-1.5 animate-ping rounded-full bg-primary" />
}
