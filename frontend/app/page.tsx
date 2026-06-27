import { SiteHeader } from "@/components/site-header"
import { UrlInputForm } from "@/components/url-input-form"
import { STEP_DEFS } from "@/lib/steps"

export default function HomePage() {
  return (
    <div className="relative flex min-h-screen flex-col">
      <div className="pointer-events-none absolute inset-0 bg-grid [mask-image:radial-gradient(ellipse_60%_50%_at_50%_30%,black,transparent)]" />
      <SiteHeader />

      <main className="relative flex flex-1 flex-col">
        <section
          id="start"
          className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center px-4 py-16 text-center sm:px-6"
        >
          <span className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 font-mono text-xs text-muted-foreground">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
            </span>
            Generative media pipeline · Backblaze B2
          </span>

          <h1 className="text-balance text-4xl font-semibold tracking-tight sm:text-5xl md:text-6xl">
            Turn your repo into a{" "}
            <span className="text-primary">3-minute demo video</span>
          </h1>

          <p className="mt-5 max-w-xl text-pretty text-base leading-relaxed text-muted-foreground sm:text-lg">
            Paste a GitHub repository and your deployed app URL. Devfields writes the script, narrates
            it, captures the walkthrough, and renders a shareable demo — with every asset stored on
            Backblaze B2.
          </p>

          <div className="mt-9 w-full max-w-xl">
            <UrlInputForm />
          </div>

          <p className="mt-4 font-mono text-xs text-muted-foreground">
            No sign-up · Runs in your browser · ~25 seconds end-to-end
          </p>
        </section>

        <section className="mx-auto w-full max-w-5xl px-4 pb-20 sm:px-6">
          <div className="mb-8 text-center">
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              The pipeline
            </h2>
          </div>
          <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {STEP_DEFS.map((step, i) => (
              <li
                key={step.id}
                className="rounded-xl border border-border bg-card/60 p-4 transition-colors hover:border-primary/40"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-primary">{String(i + 1).padStart(2, "0")}</span>
                  <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {step.provider}
                  </span>
                </div>
                <h3 className="mt-3 text-sm font-semibold">{step.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.description}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer className="relative border-t border-border/60">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:px-6">
          <p className="font-mono">devfields · generative media hackathon</p>
          <p>Backblaze B2 · GMI Cloud · ElevenLabs</p>
        </div>
      </footer>
    </div>
  )
}
