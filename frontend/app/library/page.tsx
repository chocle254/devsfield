import Link from "next/link"
import { SiteHeader } from "@/components/site-header"
import { LibraryView } from "@/components/library-view"

export const dynamic = "force-dynamic"

export const metadata = {
  title: "My videos — Devsfield",
  description: "Every demo video you've generated, stored durably on Backblaze B2.",
}

export default function LibraryPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-balance text-3xl font-bold tracking-tight text-foreground">My videos</h1>
            <p className="mt-2 text-pretty text-base leading-relaxed text-muted-foreground">
              Every demo you&apos;ve generated, restored straight from Backblaze B2 — nothing is lost on
              refresh.
            </p>
          </div>
          <Link
            href="/#start"
            className="rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            New demo
          </Link>
        </div>

        <LibraryView />
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
