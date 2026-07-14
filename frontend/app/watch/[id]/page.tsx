import { SiteHeader } from "@/components/site-header"
import { WatchView } from "@/components/watch-view"

export const dynamic = "force-dynamic"

export const metadata = {
  title: "Watch demo — Devsfield",
  description: "An AI-generated demo video, made with Devsfield.",
}

export default async function WatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        <WatchView id={id} />
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-2 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:px-6">
          <p>Devsfield</p>
          <p>Backblaze B2 · GMI Cloud · Playwright</p>
        </div>
      </footer>
    </div>
  )
}
