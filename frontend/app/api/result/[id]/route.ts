import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? process.env.BACKEND_URL
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Server misconfigured: NEXT_PUBLIC_BACKEND_URL is not set." },
      { status: 500 },
    )
  }

  let backendRes: Response
  try {
    backendRes = await fetch(`${backendUrl}/result/${id}`, { cache: "no-store" })
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "unknown error"
    return NextResponse.json({ error: `Could not reach backend: ${message}` }, { status: 502 })
  }

  const data = await backendRes.json().catch(() => null)

  if (backendRes.status === 404) {
    return NextResponse.json({ error: "Run not found." }, { status: 404 })
  }
  if (!backendRes.ok) {
    return NextResponse.json(
      { error: data?.detail ?? `Backend returned ${backendRes.status}` },
      { status: backendRes.status },
    )
  }

  return NextResponse.json({
    id,
    status: data?.status,
    result: data?.status === "complete" ? {
      videoUrl: data.video_url,
      manifestUrl: data.manifest_url,
      segmentsUrl: data.segments_url,
      segments: data.segments,
      sha256: data.sha256,
      modelsUsed: data.models_used,
      generatedAt: data.generated_at,
    } : null,
  })
}
