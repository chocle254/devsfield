export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const backendUrl = process.env.BACKEND_URL

  const sseError = (message: string) =>
    new Response(`data: ${JSON.stringify({ error: message })}\n\n`, {
      headers: { "Content-Type": "text/event-stream" },
    })

  if (!backendUrl) {
    return sseError("Server misconfigured: BACKEND_URL is not set.")
  }

  let backendRes: Response
  try {
    backendRes = await fetch(`${backendUrl}/stream/${id}`, { cache: "no-store" })
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "unknown error"
    return sseError(`Could not reach backend: ${message}`)
  }

  if (!backendRes.ok || !backendRes.body) {
    return sseError(`Backend returned ${backendRes.status}`)
  }

  return new Response(backendRes.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  })
}
