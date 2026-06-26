import { SiteHeader } from "@/components/site-header"
import { ResultView } from "@/components/result-view"

export default async function ResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <div className="relative flex min-h-screen flex-col">
      <div className="pointer-events-none absolute inset-0 bg-grid [mask-image:radial-gradient(ellipse_70%_50%_at_50%_0%,black,transparent)]" />
      <SiteHeader />
      <main className="relative mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
        <div className="mb-8 flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 13l4 4L19 7" />
            </svg>
          </span>
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-primary">Render complete</p>
          </div>
        </div>
        <h1 className="mb-8 text-2xl font-semibold tracking-tight sm:text-3xl">
          Your demo video is ready
        </h1>
        <ResultView id={id} />
      </main>
    </div>
  )
}
