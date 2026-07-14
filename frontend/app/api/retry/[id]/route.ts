import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST(_req: Request, { params }: { params: Promise<{ id: string }> }) {
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
    backendRes = await fetch(`${backendUrl}/retry/${id}`, { method: "POST" })
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

  return NextResponse.json({ id: data.job_id, status: data.status })
}
