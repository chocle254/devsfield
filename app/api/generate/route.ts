import { NextResponse } from "next/server"
import { createRun, runPipeline } from "@/lib/runner"
import { newId } from "@/lib/store"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

function isLikelyUrl(v: string) {
  try {
    const u = new URL(v)
    return u.protocol === "http:" || u.protocol === "https:"
  } catch {
    return false
  }
}

export async function POST(req: Request) {
  let body: { repoUrl?: string; appUrl?: string }
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

  const id = newId()
  createRun(id, repoUrl, appUrl)

  // Kick off the pipeline without blocking the response.
  runPipeline(id).catch((e) => {
    console.log("[v0] pipeline error:", e?.message)
  })

  return NextResponse.json({ id })
}
