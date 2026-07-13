export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; snapshotId: string }> },
) {
  const { id, snapshotId } = await params
  const backendUrl = process.env.BACKEND_URL

  if (!backendUrl) {
    return Response.json(
      { error: "Snapshot service is not configured." },
      { status: 500 },
    )
  }

  let backendResponse: Response
  try {
    backendResponse = await fetch(
      `${backendUrl}/snapshot/${encodeURIComponent(id)}/${encodeURIComponent(snapshotId)}`,
      { cache: "no-store" },
    )
  } catch {
    return Response.json(
      { error: "Snapshot service is unavailable." },
      { status: 502 },
    )
  }

  if (backendResponse.status === 404) {
    return Response.json({ error: "Snapshot not found." }, { status: 404 })
  }
  if (!backendResponse.ok || !backendResponse.body) {
    return Response.json(
      { error: "Could not load snapshot." },
      { status: 502 },
    )
  }

  return new Response(backendResponse.body, {
    headers: {
      "Content-Type": backendResponse.headers.get("content-type") ?? "image/jpeg",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  })
}
