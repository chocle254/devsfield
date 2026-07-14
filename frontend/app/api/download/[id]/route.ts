import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/**
 * Same-origin download proxy.
 *
 * The old "Download MP4" button set the `download` attribute on an anchor
 * pointing at the cross-origin Backblaze URL. Browsers IGNORE `download` for
 * cross-origin links, so it either opened the video inline or failed with
 * "No file". This route fetches the current video URL from the backend (which
 * mints a fresh presigned URL), streams the bytes back from OUR origin, and
 * sets Content-Disposition: attachment so the browser actually saves the file.
 */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const backendUrl = process.env.BACKEND_URL
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Server misconfigured: BACKEND_URL is not set." },
      { status: 500 },
    )
  }

  // 1. Ask the backend for the current (freshly-signed) video URL.
  let resultRes: Response
  try {
    resultRes = await fetch(`${backendUrl}/download/${id}`, { cache: "no-store" })
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "unknown error"
    return NextResponse.json({ error: `Could not reach backend: ${message}` }, { status: 502 })
  }

  const result = await resultRes.json().catch(() => null)
  if (!resultRes.ok) {
    return NextResponse.json(
      { error: result?.detail ?? "Video not found." },
      { status: resultRes.status },
    )
  }

  const videoUrl: string | undefined = result?.video_url
  if (!videoUrl) {
    return NextResponse.json({ error: "This video has no downloadable file." }, { status: 404 })
  }

  // 2. Stream the actual video bytes from B2 through our origin.
  let fileRes: Response
  try {
    fileRes = await fetch(videoUrl, { cache: "no-store" })
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "unknown error"
    return NextResponse.json({ error: `Could not fetch video: ${message}` }, { status: 502 })
  }

  if (!fileRes.ok || !fileRes.body) {
    return NextResponse.json({ error: "Could not fetch video file." }, { status: 502 })
  }

  const repoName =
    (typeof result?.repo_name === "string" && result.repo_name.trim()) || "demo"
  const safeName = repoName.replace(/[^a-zA-Z0-9-_]/g, "-").toLowerCase()
  const filename = `${safeName}-${id.slice(0, 8)}.mp4`

  const headers = new Headers()
  headers.set("Content-Type", fileRes.headers.get("Content-Type") || "video/mp4")
  const len = fileRes.headers.get("Content-Length")
  if (len) headers.set("Content-Length", len)
  headers.set("Content-Disposition", `attachment; filename="${filename}"`)
  headers.set("Cache-Control", "no-store")

  return new NextResponse(fileRes.body, { status: 200, headers })
}
