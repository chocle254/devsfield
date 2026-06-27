"use client"

import { useRouter } from "next/navigation"
import { useRef, useState } from "react"
import type { VideoFormat } from "@/lib/types"

const DURATIONS = [
  { sec: 60, label: "1 min" },
  { sec: 90, label: "90 sec" },
  { sec: 180, label: "3 min" },
  { sec: 300, label: "5 min" },
]

export function UrlInputForm() {
  const router = useRouter()
  const [repoUrl, setRepoUrl] = useState("")
  const [appUrl, setAppUrl] = useState("")
  const [maxDurationSec, setMaxDurationSec] = useState(180)
  const [format, setFormat] = useState<VideoFormat>("demo")
  const [presenterOn, setPresenterOn] = useState(false)
  const [presenterName, setPresenterName] = useState("")
  const [presenterPhoto, setPresenterPhoto] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repoUrl,
          appUrl,
          options: {
            maxDurationSec,
            format,
            presenter: {
              enabled: presenterOn,
              name: presenterName || undefined,
              photoUrl: presenterOn ? presenterPhoto ?? undefined : undefined,
            },
          },
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.error ?? "Something went wrong.")
        setLoading(false)
        return
      }
      router.push(`/run/${data.id}`)
    } catch {
      setError("Network error. Please try again.")
      setLoading(false)
    }
  }

  function fillExample() {
    setRepoUrl("https://github.com/vercel/next.js")
    setAppUrl("https://nextjs.org")
  }

  function onPhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith("image/")) {
      setError("Please upload an image file for the presenter.")
      return
    }
    if (file.size > 4 * 1024 * 1024) {
      setError("Presenter photo must be under 4 MB.")
      return
    }
    const reader = new FileReader()
    reader.onload = () => setPresenterPhoto(typeof reader.result === "string" ? reader.result : null)
    reader.readAsDataURL(file)
  }

  return (
    <form
      onSubmit={onSubmit}
      className="w-full rounded-xl border border-border bg-card p-2 text-left shadow-2xl shadow-black/40"
    >
      <Field
        label="GitHub repository"
        icon={<GitIcon />}
        placeholder="https://github.com/owner/repo"
        value={repoUrl}
        onChange={setRepoUrl}
        autoFocus
      />
      <div className="h-px bg-border" />
      <Field
        label="Deployed app URL"
        icon={<GlobeIcon />}
        placeholder="https://your-app.vercel.app"
        value={appUrl}
        onChange={setAppUrl}
      />

      {/* Options */}
      <div className="mt-1 space-y-3 rounded-lg border border-border bg-background/40 p-3">
        {/* Max duration */}
        <div>
          <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            Max length
          </p>
          <div className="flex flex-wrap gap-1.5">
            {DURATIONS.map((d) => (
              <Chip key={d.sec} active={maxDurationSec === d.sec} onClick={() => setMaxDurationSec(d.sec)}>
                {d.label}
              </Chip>
            ))}
          </div>
        </div>

        {/* Format */}
        <div>
          <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            What to include
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            <SegButton active={format === "demo"} onClick={() => setFormat("demo")}>
              Demo only
            </SegButton>
            <SegButton active={format === "pitch_demo"} onClick={() => setFormat("pitch_demo")}>
              Pitch + demo
            </SegButton>
          </div>
        </div>

        {/* Presenter */}
        <div>
          <button
            type="button"
            onClick={() => setPresenterOn((v) => !v)}
            className="flex w-full items-center justify-between gap-3 text-left"
            aria-pressed={presenterOn}
          >
            <span className="flex flex-col">
              <span className="text-sm font-medium text-foreground">Presenter cam</span>
              <span className="text-xs text-muted-foreground">
                Add a Zoom-style talking head from your photo
              </span>
            </span>
            <span
              className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                presenterOn ? "bg-primary" : "bg-input"
              }`}
            >
              <span
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-background transition-transform ${
                  presenterOn ? "translate-x-4" : "translate-x-0.5"
                }`}
              />
            </span>
          </button>

          {presenterOn ? (
            <div className="mt-3 flex items-center gap-3">
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-input text-muted-foreground transition-colors hover:border-primary/50"
                aria-label="Upload presenter photo"
              >
                {presenterPhoto ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={presenterPhoto || "/placeholder.svg"} alt="Presenter preview" className="h-full w-full object-cover" />
                ) : (
                  <CameraIcon />
                )}
              </button>
              <input ref={fileRef} type="file" accept="image/*" onChange={onPhoto} className="hidden" />
              <div className="flex min-w-0 flex-1 flex-col">
                <input
                  type="text"
                  value={presenterName}
                  onChange={(e) => setPresenterName(e.target.value)}
                  placeholder="Your name (optional)"
                  className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/50"
                />
                <span className="mt-1 text-[11px] text-muted-foreground">
                  {presenterPhoto ? "Photo added — animated as you present." : "Upload a clear, front-facing photo."}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex flex-col gap-2 px-1 pb-1 pt-2 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          onClick={fillExample}
          className="text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          Try an example →
        </button>
        <button
          type="submit"
          disabled={loading}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? (
            <>
              <Spinner /> Spinning up pipeline…
            </>
          ) : (
            <>
              Generate demo video <ArrowIcon />
            </>
          )}
        </button>
      </div>

      {error ? (
        <p className="px-2 pb-1.5 pt-1 text-xs font-medium text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  )
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border bg-background text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  )
}

function SegButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border bg-background text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  )
}

function Field({
  label,
  icon,
  placeholder,
  value,
  onChange,
  autoFocus,
}: {
  label: string
  icon: React.ReactNode
  placeholder: string
  value: string
  onChange: (v: string) => void
  autoFocus?: boolean
}) {
  return (
    <label className="group flex items-center gap-3 rounded-lg px-3 py-3 transition-colors focus-within:bg-input/60">
      <span className="text-muted-foreground transition-colors group-focus-within:text-primary">{icon}</span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{label}</span>
        <input
          type="url"
          required
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/60"
        />
      </span>
    </label>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin" width="15" height="15" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

function ArrowIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  )
}

function CameraIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </svg>
  )
}

function GitIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.7 1.3 3.4 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5Z" />
    </svg>
  )
}

function GlobeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  )
}
