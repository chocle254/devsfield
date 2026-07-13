"use client"

import { useState } from "react"

const DURATIONS = [
  { sec: 60, label: "1m" },
  { sec: 180, label: "3m" },
  { sec: 300, label: "5m" },
]

// Template presets map directly to the backend `tone` field.
const TEMPLATES = [
  { value: "pitch", label: "Professional" },
  { value: "demo", label: "Conversational" },
  { value: "technical", label: "Technical" },
  { value: "pitch_demo", label: "Pitch + demo" },
]

interface UrlInputFormProps {
  onStarted: (id: string) => void
  running: boolean
}

export function UrlInputForm({ onStarted, running }: UrlInputFormProps) {
  const [repoUrl, setRepoUrl] = useState("")
  const [appUrl, setAppUrl] = useState("")
  const [maxDurationSec, setMaxDurationSec] = useState(180)
  const [tone, setTone] = useState("pitch")
  const [loginOn, setLoginOn] = useState(false)
  const [loginUsername, setLoginUsername] = useState("")
  const [loginPassword, setLoginPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const disabled = loading || running

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (disabled) return
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
            tone,
            credentials:
              loginOn && loginUsername && loginPassword
                ? { username: loginUsername, password: loginPassword }
                : undefined,
          },
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.error ?? "Something went wrong.")
        setLoading(false)
        return
      }
      onStarted(data.id)
      setLoading(false)
    } catch {
      setError("Network error. Please try again.")
      setLoading(false)
    }
  }

  function reset() {
    setRepoUrl("")
    setAppUrl("")
    setMaxDurationSec(180)
    setTone("pitch")
    setLoginOn(false)
    setLoginUsername("")
    setLoginPassword("")
    setError(null)
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {/* Generation mode tabs */}
      <div className="grid grid-cols-2 gap-1 rounded-xl border border-border bg-card p-1">
        <span className="rounded-lg bg-secondary px-4 py-2.5 text-center text-sm font-semibold text-foreground shadow-sm ring-1 ring-border">
          Single generation
        </span>
        <span className="flex items-center justify-center gap-1.5 rounded-lg px-4 py-2.5 text-center text-sm font-medium text-muted-foreground">
          Batch generation
          <SoonBadge />
        </span>
      </div>

      {/* Repository and site */}
      <Card title="Repository and site" subtitle="Paste the links you want Devsfield to analyze and navigate.">
        <TextField
          label="GitHub repository URL"
          type="url"
          required
          value={repoUrl}
          onChange={setRepoUrl}
          placeholder="https://github.com/username/repo"
          disabled={disabled}
        />
        <TextField
          label="Deployed site URL"
          type="url"
          required
          value={appUrl}
          onChange={setAppUrl}
          placeholder="https://my-app.vercel.app"
          disabled={disabled}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <FieldLabel>Duration</FieldLabel>
            <div className="grid grid-cols-3 gap-1 rounded-lg border border-border p-1">
              {DURATIONS.map((d) => (
                <button
                  key={d.sec}
                  type="button"
                  disabled={disabled}
                  onClick={() => setMaxDurationSec(d.sec)}
                  className={`rounded-md py-2 text-sm font-medium transition-colors disabled:opacity-60 ${
                    maxDurationSec === d.sec
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <FieldLabel>
              Video quality <SoonBadge />
            </FieldLabel>
            <SelectShell disabled>1080p Full HD</SelectShell>
          </div>
        </div>
      </Card>

      {/* Voiceover & style */}
      <Card title="Voiceover & style">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <FieldLabel>
              Language <SoonBadge />
            </FieldLabel>
            <SelectShell disabled>English</SelectShell>
          </div>
          <div>
            <FieldLabel>
              Voice <SoonBadge />
            </FieldLabel>
            <SelectShell disabled>Default</SelectShell>
          </div>
        </div>

        <div className="sm:w-1/2 sm:pr-2">
          <FieldLabel>Template</FieldLabel>
          <div className="relative">
            <select
              value={tone}
              disabled={disabled}
              onChange={(e) => setTone(e.target.value)}
              className="w-full appearance-none rounded-lg border border-border bg-card px-3 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-ring disabled:opacity-60"
            >
              {TEMPLATES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <ChevronIcon />
          </div>
        </div>
      </Card>

      {/* Enhancements */}
      <Card title="Enhancements">
        <ToggleRow
          title="Demo login"
          subtitle="App behind a login? Add a demo account so the AI can sign in."
          checked={loginOn}
          onChange={() => setLoginOn((v) => !v)}
          disabled={disabled}
        />
        {loginOn ? (
          <div className="grid grid-cols-1 gap-2 rounded-lg border border-border bg-secondary/60 p-3 sm:grid-cols-2">
            <input
              type="text"
              autoComplete="off"
              value={loginUsername}
              onChange={(e) => setLoginUsername(e.target.value)}
              placeholder="Demo email or username"
              disabled={disabled}
              className="w-full rounded-md border border-border bg-card px-2.5 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-ring"
            />
            <input
              type="password"
              autoComplete="new-password"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              placeholder="Demo password"
              disabled={disabled}
              className="w-full rounded-md border border-border bg-card px-2.5 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-ring"
            />
            <p className="text-[11px] leading-relaxed text-muted-foreground sm:col-span-2">
              Used once during recording and never stored. The login screen is kept out of the final video.
            </p>
          </div>
        ) : null}

        <div className="h-px bg-border" />

        <ToggleRow title="Background music" subtitle="Add a subtle music bed under the voiceover." soon />
        <ToggleRow title="Subtitles / captions" subtitle="Burn captions into the final video." soon />
        <ToggleRow title="Watermark" subtitle="Add a small branded mark in the corner." soon />
      </Card>

      {error ? (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex items-center justify-end gap-3">
        <button
          type="button"
          onClick={reset}
          disabled={disabled}
          className="rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-secondary disabled:opacity-60"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={disabled}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? (
            <>
              <Spinner /> Starting…
            </>
          ) : running ? (
            <>
              <WandIcon /> Generating…
            </>
          ) : (
            <>
              <WandIcon /> Generate video
            </>
          )}
        </button>
      </div>
    </form>
  )
}

function Card({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {subtitle ? <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p> : null}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  )
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-foreground">
      {children}
    </span>
  )
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  required,
  disabled,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  required?: boolean
  disabled?: boolean
}) {
  return (
    <label className="block">
      <FieldLabel>{label}</FieldLabel>
      <input
        type={type}
        required={required}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-border bg-accent/40 px-3 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-primary focus:bg-card focus:ring-2 focus:ring-ring disabled:opacity-60"
      />
    </label>
  )
}

function SelectShell({ children, disabled }: { children: React.ReactNode; disabled?: boolean }) {
  return (
    <div
      className={`relative flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2.5 text-sm ${
        disabled ? "text-muted-foreground" : "text-foreground"
      }`}
      aria-disabled={disabled}
    >
      <span>{children}</span>
      <ChevronIcon static />
    </div>
  )
}

function ToggleRow({
  title,
  subtitle,
  checked = false,
  onChange,
  disabled,
  soon,
}: {
  title: string
  subtitle: string
  checked?: boolean
  onChange?: () => void
  disabled?: boolean
  soon?: boolean
}) {
  const inactive = soon || disabled
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          {title}
          {soon ? <SoonBadge /> : null}
        </p>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={title}
        disabled={inactive}
        onClick={onChange}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
          checked ? "bg-primary" : "bg-border"
        } ${inactive ? "cursor-not-allowed opacity-60" : ""}`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-card shadow transition-transform ${
            checked ? "translate-x-[22px]" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  )
}

function SoonBadge() {
  return (
    <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground ring-1 ring-border">
      Soon
    </span>
  )
}

function ChevronIcon({ static: isStatic }: { static?: boolean }) {
  return (
    <svg
      className={
        isStatic
          ? "text-muted-foreground"
          : "pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground"
      }
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

function WandIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m3 21 9-9M15 4V2M15 10V8M12 7h-2M20 7h-2M17 5 15.5 6.5M17 9l-1.5-1.5" />
    </svg>
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
