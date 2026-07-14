import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/**
 * Permanently deletes a video and all of its assets from Backblaze B2.
 * Irreversible — the UI guards this behind a confirmation dialog.
 */
export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const backendUrl = process.env.BACKEND_URL
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Server misconfigured: BACKEND_URL is not set." },
      { status: 500 },
    )
  }

  let backendRes: Response
  try {
    backendRes = await fetch(`${backendUrl}/library/${id}`, {
      method: "DELETE",
      cache: "no-store",
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

  return NextResponse.json({ id, deleted: true })
}
