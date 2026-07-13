"use client"

import { useState } from "react"
import { SiteHeader } from "@/components/site-header"
import { UrlInputForm } from "@/components/url-input-form"
import { PipelineView } from "@/components/pipeline-view"

export default function HomePage() {
  const [runId, setRunId] = useState<string | null>(null)

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 sm:px-6 sm:py-10" id="start">
        <div className="mb-6">
          <h1 className="text-balance text-3xl font-bold tracking-tight text-foreground">
            Generate demo video
          </h1>
          <p className="mt-2 text-pretty text-base leading-relaxed text-muted-foreground">
            Configure how Devsfield analyzes your repository and presents it on screen.
          </p>
        </div>

        {runId ? (
          <div className="mb-8">
            <PipelineView id={runId} />
          </div>
        ) : null}

        <UrlInputForm onStarted={setRunId} running={!!runId} />
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-2 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:px-6">
          <p>Devsfield</p>
          <p>Backblaze B2 · GMI Cloud · Playwright</p>
        </div>
      </footer>
    </div>
  )
}
