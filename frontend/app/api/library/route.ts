import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/**
 * Lists every completed demo video from the backend, which reads them
 * straight off Backblaze B2. Because it's backed by durable storage (not
 * in-memory job state), the library is complete after any refresh or redeploy.
 */
export async function GET() {
  const backendUrl = process.env.BACKEND_URL
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Server misconfigured: BACKEND_URL is not set." },
      { status: 500 },
    )
  }

  let backendRes: Response
  try {
    backendRes = await fetch(`${backendUrl}/library`, { cache: "no-store" })
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

  const rawVideos: Array<Record<string, unknown>> = Array.isArray(data?.videos) ? data.videos : []

  // Map backend fields → the shape the library UI expects.
  const videos = rawVideos.map((v) => {
    const jobId = typeof v.job_id === "string" ? v.job_id : ""
    const repoName =
      (typeof v.repo_name === "string" && v.repo_name.trim()) || ""
    return {
      id: jobId,
      title: repoName ? `${repoName} — Demo` : `Demo ${jobId.slice(0, 8)}`,
      repoName: repoName || null,
      githubUrl: typeof v.github_url === "string" ? v.github_url : null,
      appUrl: typeof v.app_url === "string" ? v.app_url : null,
      tone: typeof v.tone === "string" ? v.tone : null,
      durationSec: typeof v.duration_seconds === "number" ? v.duration_seconds : null,
      generatedAt: typeof v.generated_at === "string" ? v.generated_at : null,
      videoUrl: typeof v.video_url === "string" ? v.video_url : null,
      status: "complete" as const,
    }
  })

  return NextResponse.json({ videos })
}
