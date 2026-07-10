import type { Metadata } from "next"
import { SiteHeader } from "@/components/site-header"

export const metadata: Metadata = {
  title: "API Docs — devfields",
  description:
    "Use the devfields HTTP API to generate AI demo videos from any GitHub repo and deployed app.",
}

const ENDPOINTS = [
  {
    method: "POST",
    path: "/generate",
    summary: "Start a video generation job",
    detail:
      "Kicks off the full pipeline: repo analysis, demo planning, screen recording, narration, voiceover, and assembly. Returns a job_id immediately.",
  },
  {
    method: "GET",
    path: "/status/{job_id}",
    summary: "Poll job status",
    detail:
      "Returns the current pipeline step, per-step progress, and the final result once complete.",
  },
  {
    method: "GET",
    path: "/stream/{job_id}",
    summary: "Stream progress (SSE)",
    detail:
      "Server-Sent Events stream of live progress updates — the same feed the devfields UI uses.",
  },
  {
    method: "GET",
    path: "/result/{job_id}",
    summary: "Fetch the result",
    detail:
      "Returns the final video URL plus every per-segment clip, voice track, and the provenance manifest.",
  },
]

const REQUEST_FIELDS = [
  {
    name: "github_url",
    type: "string",
    required: true,
    detail: "Public GitHub repository URL. The AI studies it to plan the demo.",
  },
  {
    name: "app_url",
    type: "string",
    required: true,
    detail: "Your deployed app URL — this is what gets recorded.",
  },
  {
    name: "video_length",
    type: "number",
    required: false,
    detail:
      "Target length in seconds, 60-300 (default 180). A hard cap: slow pages cause low-priority beats to be dropped, never a longer video.",
  },
  {
    name: "tone",
    type: "string",
    required: false,
    detail:
      'One of "pitch", "pitch_demo", "demo", or "technical" (default "pitch"). Each tone uses its own curated narration voice.',
  },
  {
    name: "credentials",
    type: "object",
    required: false,
    detail:
      "Optional { username, password } demo account for apps behind a login. Used once during recording, never stored; the sign-in is kept out of the final video.",
  },
]

const EXAMPLE_REQUEST = `curl -X POST https://your-backend/generate \\
  -H "Content-Type: application/json" \\
  -d '{
    "github_url": "https://github.com/you/your-app",
    "app_url": "https://your-app.vercel.app",
    "video_length": 180,
    "tone": "pitch",
    "credentials": {
      "username": "demo@example.com",
      "password": "demo1234"
    }
  }'`

const EXAMPLE_RESPONSE = `{
  "job_id": "b3f1c9e2-4a7d-4f0e-9c2a-1d8e5f6a7b8c",
  "status": "queued"
}`

const VOICES = [
  { tone: "pitch", voice: "Adam", style: "Deep, confident announcer — investor pitch energy" },
  { tone: "pitch_demo", voice: "George", style: "Warm narrator — pitch that flows into a demo" },
  { tone: "demo", voice: "Sarah", style: "Conversational and friendly — product walkthrough" },
  { tone: "technical", voice: "Rachel", style: "Clear and precise — technical deep-dive" },
]

export default function DocsPage() {
  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden">
      <div className="aurora-field" />
      <SiteHeader />

      <main className="relative mx-auto w-full max-w-3xl flex-1 px-4 py-14 sm:px-6">
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-white/[0.03] px-3 py-1 font-mono text-[11px] tracking-wide text-muted-foreground backdrop-blur-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          HTTP API · v1
        </span>

        <h1 className="mt-6 text-balance font-display text-4xl italic leading-[1.1] tracking-tight sm:text-5xl">
          API <span className="not-italic text-primary">reference</span>
        </h1>
        <p className="mt-4 max-w-xl text-pretty leading-relaxed text-muted-foreground">
          Everything the devfields UI does is available as a plain HTTP API. Start a
          job, stream its progress, and fetch the finished video — no SDK required.
        </p>

        {/* Endpoints */}
        <SectionHeading>Endpoints</SectionHeading>
        <ul className="flex flex-col gap-3">
          {ENDPOINTS.map((ep) => (
            <li key={ep.path} className="glass-panel rounded-xl p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold ${
                    ep.method === "POST"
                      ? "bg-primary text-primary-foreground"
                      : "border border-border text-muted-foreground"
                  }`}
                >
                  {ep.method}
                </span>
                <code className="font-mono text-sm text-foreground">{ep.path}</code>
              </div>
              <h3 className="mt-2 text-sm font-medium">{ep.summary}</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{ep.detail}</p>
            </li>
          ))}
        </ul>

        {/* Request body */}
        <SectionHeading>Request body — POST /generate</SectionHeading>
        <div className="glass-panel overflow-hidden rounded-xl">
          <ul className="divide-y divide-border/60">
            {REQUEST_FIELDS.map((f) => (
              <li key={f.name} className="flex flex-col gap-1 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <code className="font-mono text-sm text-foreground">{f.name}</code>
                  <span className="font-mono text-[11px] text-muted-foreground">{f.type}</span>
                  <span
                    className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
                      f.required
                        ? "border-primary/40 text-primary"
                        : "border-border text-muted-foreground"
                    }`}
                  >
                    {f.required ? "required" : "optional"}
                  </span>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground">{f.detail}</p>
              </li>
            ))}
          </ul>
        </div>

        {/* Example */}
        <SectionHeading>Example</SectionHeading>
        <div className="flex flex-col gap-3">
          <CodeBlock label="Request" code={EXAMPLE_REQUEST} />
          <CodeBlock label="Response" code={EXAMPLE_RESPONSE} />
        </div>

        {/* Voices */}
        <SectionHeading>Narration voices</SectionHeading>
        <p className="mb-4 text-sm leading-relaxed text-muted-foreground">
          Each tone maps to one curated voice, so the whole video sounds like a single
          person presenting. Narration is written from what&apos;s actually on screen
          and word-fitted to each segment&apos;s duration.
        </p>
        <div className="glass-panel overflow-hidden rounded-xl">
          <ul className="divide-y divide-border/60">
            {VOICES.map((v) => (
              <li key={v.tone} className="flex flex-col gap-0.5 p-4 sm:flex-row sm:items-center sm:gap-4">
                <code className="w-28 shrink-0 font-mono text-sm text-primary">{v.tone}</code>
                <span className="w-20 shrink-0 text-sm font-medium">{v.voice}</span>
                <span className="text-xs leading-relaxed text-muted-foreground">{v.style}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Timing */}
        <SectionHeading>How timing works</SectionHeading>
        <ul className="flex flex-col gap-2 text-sm leading-relaxed text-muted-foreground">
          <li className="glass-panel rounded-xl p-4">
            <span className="font-medium text-foreground">Hard budget.</span> The planner
            allocates seconds per demo beat so the total fits your requested length.
          </li>
          <li className="glass-panel rounded-xl p-4">
            <span className="font-medium text-foreground">Priority ordering.</span> If pages
            load slowly, the lowest-priority beats are dropped — your best feature always
            makes the cut.
          </li>
          <li className="glass-panel rounded-xl p-4">
            <span className="font-medium text-foreground">No dead air.</span> Each
            segment&apos;s clock starts only after the page settles, so spinners and blank
            screens never appear in the final video.
          </li>
        </ul>
      </main>

      <footer className="relative border-t border-border/60">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:px-6">
          <p className="font-mono">devfields · generative media hackathon</p>
          <p>Backblaze B2 · GMI Cloud · ElevenLabs</p>
        </div>
      </footer>
    </div>
  )
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-4 mt-12 flex items-center gap-3">
      <span className="h-px flex-1 bg-border" />
      <h2 className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
        {children}
      </h2>
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  return (
    <div className="glass-panel overflow-hidden rounded-xl">
      <div className="border-b border-border/60 px-4 py-2 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  )
}
