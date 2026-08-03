import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const DURATION_MIN = 60
const DURATION_MAX = 300
const ALLOWED_TONES = ["pitch", "demo", "technical", "pitch_demo"] as const

// Mirrors backend/models.py + backend/pipeline/demo_planner.py so a
// malformed scene never reaches the backend as anything but dropped/trimmed
// input — the backend re-validates and re-sanitizes regardless, this just
// avoids a confusing 422 for garden-variety stray whitespace or over-length
// text.
const SAFE_ACTIONS = ["click", "type", "select", "toggle", "press", "scroll"]
const MAX_BEATS = 10
const MAX_STEPS_PER_BEAT = 5

function isLikelyUrl(v: string) {
  try {
    const u = new URL(v)
    return u.protocol === "http:" || u.protocol === "https:"
  } catch {
    return false
  }
}

type StoryboardStepInput = {
  action?: string
  target?: string
  value?: string
  expected_result?: string
}

type StoryboardBeatInput = {
  route?: string
  feature?: string
  actions_hint?: string
  talking_point?: string
  seconds?: number
  interaction_steps?: StoryboardStepInput[]
}

type RequestBody = {
  repoUrl?: string
  appUrl?: string
  options?: {
    maxDurationSec?: number
    tone?: string
    /** voice preference ("male" or "female") sent to the backend */
    voice?: string
    /** @deprecated legacy field from the old mock form, mapped to `tone` below */
    format?: string
    /** optional demo-account login for apps behind authentication */
    credentials?: { username?: string; password?: string }
    /** developer-authored shot list; skips AI planning when present */
    storyboard?: StoryboardBeatInput[]
  }
}

/** Returns undefined when there's nothing usable, so the backend falls back
 * to its normal AI-planned behavior instead of receiving an empty array. */
function sanitizeStoryboard(raw: StoryboardBeatInput[] | undefined) {
  if (!Array.isArray(raw) || raw.length === 0) return undefined

  const beats = raw.slice(0, MAX_BEATS).map((beat) => {
    const interaction_steps = Array.isArray(beat.interaction_steps)
      ? beat.interaction_steps
          .slice(0, MAX_STEPS_PER_BEAT)
          .map((s) => ({
            action: (s.action ?? "").toLowerCase().trim(),
            target: (s.target ?? "").trim().slice(0, 120),
            value: s.value?.trim().slice(0, 240) || undefined,
            expected_result: s.expected_result?.trim().slice(0, 180) || undefined,
          }))
          .filter((s) => SAFE_ACTIONS.includes(s.action) && s.target)
      : []

    return {
      route: (beat.route || "/").trim().slice(0, 200) || "/",
      feature: beat.feature?.trim().slice(0, 160) || undefined,
      actions_hint: beat.actions_hint?.trim().slice(0, 300) || undefined,
      talking_point: beat.talking_point?.trim().slice(0, 300) || undefined,
      seconds: Number.isFinite(beat.seconds) ? beat.seconds : undefined,
      interaction_steps,
    }
  })

  return beats.length > 0 ? beats : undefined
}

export async function POST(req: Request) {
  const backendUrl = process.env.BACKEND_URL
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Server misconfigured: BACKEND_URL is not set." },
      { status: 500 },
    )
  }

  let body: RequestBody
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 })
  }

  const repoUrl = (body.repoUrl ?? "").trim()
  const appUrl = (body.appUrl ?? "").trim()

  if (!isLikelyUrl(repoUrl) || !repoUrl.includes("github.com")) {
    return NextResponse.json({ error: "Enter a valid GitHub repository URL." }, { status: 400 })
  }
  if (!isLikelyUrl(appUrl)) {
    return NextResponse.json({ error: "Enter a valid deployed app URL." }, { status: 400 })
  }

  // video_length: backend requires 60-300, default 180
  const rawDuration = Number(body.options?.maxDurationSec)
  const video_length = Number.isFinite(rawDuration)
    ? Math.min(DURATION_MAX, Math.max(DURATION_MIN, Math.round(rawDuration)))
    : 180

  // tone: prefer the new field; fall back to the old mock form's `format`
  // field (pitch_demo -> pitch, demo -> demo) until the UI is updated.
  let tone = body.options?.tone
  if (!tone && body.options?.format) {
    tone = body.options.format === "pitch_demo" ? "pitch_demo" : "demo"
  }
  if (!tone || !(ALLOWED_TONES as readonly string[]).includes(tone)) {
    tone = "pitch"
  }

  // Optional voice preference: only forward a known value so the backend
  // falls back to its tone-based default for anything unexpected.
  const ALLOWED_VOICES = ["male", "female"]
  const rawVoice = body.options?.voice?.trim().toLowerCase()
  const voice = rawVoice && ALLOWED_VOICES.includes(rawVoice) ? rawVoice : undefined

  // Optional demo login: only forwarded when both fields are present.
  // Passed straight through to the backend for the recording session —
  // never logged or persisted here.
  const rawCreds = body.options?.credentials
  const credentials =
    rawCreds?.username?.trim() && rawCreds?.password
      ? { username: rawCreds.username.trim(), password: rawCreds.password }
      : undefined

  const storyboard = sanitizeStoryboard(body.options?.storyboard)

  let backendRes: Response
  try {
    backendRes = await fetch(`${backendUrl}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        github_url: repoUrl,
        app_url: appUrl,
        video_length,
        tone,
        voice,
        credentials,
        storyboard,
      }),
    })
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "unknown error"
    return NextResponse.json({ error: `Could not reach backend: ${message}` }, { status: 502 })
  }

  const data = await backendRes.json().catch(() => null)

  if (!backendRes.ok) {
    return NextResponse.json(
      { error: data?.detail ?? `Backend returned ${backendRes.status}` },
      { status: backendRes.status },
    )
  }

  // Normalize to { id } so the rest of the app (run page redirect, etc.)
  // doesn't need to know about the backend's `job_id` naming.
  return NextResponse.json({ id: data.job_id, status: data.status })
}
