import { NextResponse } from "next/server"
import { createRun, runPipeline } from "@/lib/runner"
import { newId } from "@/lib/store"
import type { VideoOptions } from "@/lib/types"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const ALLOWED_DURATIONS = [60, 90, 180, 300]

function isLikelyUrl(v: string) {
  try {
    const u = new URL(v)
    return u.protocol === "http:" || u.protocol === "https:"
  } catch {
    return false
  }
}

function normalizeOptions(raw: any): VideoOptions {
  const maxDurationSec = ALLOWED_DURATIONS.includes(Number(raw?.maxDurationSec))
    ? Number(raw.maxDurationSec)
    : 180
  const format = raw?.format === "pitch_demo" ? "pitch_demo" : "demo"
  const enabled = Boolean(raw?.presenter?.enabled)
  const photoRaw = raw?.presenter?.photoUrl
  const photoUrl =
    enabled && typeof photoRaw === "string" && photoRaw.startsWith("data:image")
      ? photoRaw.slice(0, 3_000_000)
      : undefined
  const name =
    typeof raw?.presenter?.name === "string" && raw.presenter.name.trim()
      ? raw.presenter.name.trim().slice(0, 60)
      : undefined
  return { maxDurationSec, format, presenter: { enabled, name, photoUrl } }
}

export async function POST(req: Request) {
  let body: { repoUrl?: string; appUrl?: string; options?: unknown }
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

  const options = normalizeOptions(body.options)

  const id = newId()
  createRun(id, repoUrl, appUrl, options)

  // Kick off the pipeline without blocking the response.
  runPipeline(id).catch((e) => {
    console.log("[v0] pipeline error:", e?.message)
  })

  return NextResponse.json({ id })
}
