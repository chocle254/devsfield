import { SiteHeader } from "@/components/site-header"
import { PipelineView } from "@/components/pipeline-view"

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <div className="relative flex min-h-screen flex-col">
      <div className="pointer-events-none absolute inset-0 bg-grid [mask-image:radial-gradient(ellipse_70%_60%_at_50%_0%,black,transparent)]" />
      <SiteHeader />
      <main className="relative mx-auto w-full max-w-2xl flex-1 px-4 py-12 sm:px-6">
        <div className="mb-8">
          <p className="font-mono text-xs uppercase tracking-widest text-primary">Generating</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Building your demo video
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Run <span className="font-mono text-foreground">{id}</span> · streaming live from the pipeline
          </p>
        </div>
        <PipelineView id={id} />
      </main>
    </div>
  )
}
