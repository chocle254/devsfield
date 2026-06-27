import { NextResponse } from "next/server"
import { getRun, saveRun } from "@/lib/store"
import { applyEditToResult, interpretAndApply, rehashChangedAssets } from "@/lib/editor"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

// Simulate the time it takes to re-render only the affected segment.
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const run = getRun(id)
  if (!run || !run.result) {
    return NextResponse.json({ error: "Run not found or not finished." }, { status: 404 })
  }

  let instruction = ""
  try {
    const body = await req.json()
    instruction = String(body?.instruction ?? "").trim()
  } catch {
    // ignore
  }
  if (!instruction) {
    return NextResponse.json({ error: "Empty instruction." }, { status: 400 })
  }

  const result = run.result
  const outcome = interpretAndApply(result.scenes, result.durationSec, instruction)

  // Targeted re-render: only the changed assets get a new fingerprint.
  const newVersion = result.version + 1
  const assets = await rehashChangedAssets(result.assets, outcome.patch.changedAssets, newVersion)

  // Simulate render latency proportional to how much changed.
  await sleep(outcome.patch.action === "noop" ? 200 : 1100)

  const [userMsg, botMsg] = applyEditToResult(result, outcome, instruction)

  run.result = {
    ...result,
    scenes: outcome.scenes,
    durationSec: outcome.durationSec,
    assets,
    version: newVersion,
    edits: [...result.edits, userMsg, botMsg],
    // bust the poster/video cache visually with a version query param
    videoUrl: result.videoUrl.split("?")[0] + `?v=${newVersion}`,
  }
  saveRun(run)

  return NextResponse.json({
    ok: true,
    patch: outcome.patch,
    messages: [userMsg, botMsg],
    result: run.result,
  })
}
