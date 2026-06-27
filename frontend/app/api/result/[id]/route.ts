import { NextResponse } from "next/server"
import { getRun } from "@/lib/store"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const run = getRun(id)
  if (!run) {
    return NextResponse.json({ error: "Run not found." }, { status: 404 })
  }
  return NextResponse.json({
    id: run.id,
    status: run.status,
    repoUrl: run.repoUrl,
    appUrl: run.appUrl,
    result: run.result ?? null,
  })
}
