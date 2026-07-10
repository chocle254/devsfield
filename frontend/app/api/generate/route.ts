import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const DURATION_MIN = 60
const DURATION_MAX = 300
const ALLOWED_TONES = ["pitch", "demo", "technical", "pitch_demo"] as const

function isLikelyUrl(v: string) {
  try {
    const u = new URL(v)
    return u.protocol === "http:" || u.protocol === "https:"
  } catch {
    return false
  }
}

type RequestBody = {
  repoUrl?: string
  appUrl?: string
  options?: {
    maxDurationSec?: number
    tone?: string
    /** @deprecated legacy field from the old mock form, mapped to `tone` below */
    format?: string
  }
}

export async function POST(req: Request) {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? process.env.BACKEND_URL
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Server misconfigured: NEXT_PUBLIC_BACKEND_URL is not set." },
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
