import { SiteHeader } from "@/components/site-header"
import { PipelineView } from "@/components/pipeline-view"

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Building your demo video
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Streaming live progress from the DemoGen pipeline.
          </p>
        </div>
        <PipelineView id={id} />
      </main>
    </div>
  )
}
