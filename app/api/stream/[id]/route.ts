import { getRun } from "@/lib/store"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params

  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    async start(controller) {
      const send = (data: unknown) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`))
      }

      let closed = false
      const interval = setInterval(() => {
        const run = getRun(id)
        if (!run) {
          send({ error: "not_found" })
          clearInterval(interval)
          if (!closed) controller.close()
          closed = true
          return
        }
        send({
          id: run.id,
          status: run.status,
          steps: run.steps,
          repoUrl: run.repoUrl,
          appUrl: run.appUrl,
        })
        if (run.status === "done" || run.status === "error") {
          clearInterval(interval)
          if (!closed) controller.close()
          closed = true
        }
      }, 350)
    },
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  })
}
