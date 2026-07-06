import { SiteHeader } from "@/components/site-header"
import { UrlInputForm } from "@/components/url-input-form"
import { STEP_DEFS } from "@/lib/steps"

export default function HomePage() {
  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden">
      <div className="aurora-field" />
      <SiteHeader />

      <main className="relative flex flex-1 flex-col">
        <section
          id="start"
          className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center px-4 py-16 text-center sm:px-6"
        >
          <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-white/[0.03] px-3 py-1 font-mono text-[11px] tracking-wide text-muted-foreground backdrop-blur-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            Generative media pipeline · Backblaze B2
          </span>

          <h1 className="text-balance font-display text-5xl italic leading-[1.05] tracking-tight sm:text-6xl md:text-7xl">
            Turn your repo into a
            <br />
            <span className="not-italic text-primary">demo video</span>
          </h1>

          <p className="mt-6 max-w-xl text-pretty text-base leading-relaxed text-muted-foreground sm:text-lg">
            Paste a GitHub repository and your deployed app URL. Devfields writes the
            script, narrates it, captures the walkthrough, and renders a shareable
            demo — with every asset stored on Backblaze B2.
          </p>

          <div className="glass-panel glass-lens mt-10 w-full max-w-xl rounded-2xl p-2">
            <UrlInputForm />
          </div>

          <p className="mt-5 font-mono text-xs text-muted-foreground">
            No sign-up · Runs in your browser · ~25 seconds end-to-end
          </p>
        </section>

        <section className="mx-auto w-full max-w-5xl px-4 pb-24 sm:px-6">
          <div className="mb-8 flex items-center gap-3">
            <span className="h-px flex-1 bg-border" />
            <h2 className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
              The pipeline
            </h2>
            <span className="h-px flex-1 bg-border" />
          </div>
          <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {STEP_DEFS.map((step, i) => (
              <li
                key={step.id}
                className="glass-panel group rounded-xl p-4 transition-all duration-300 hover:border-primary/30"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-primary/80">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {step.provider}
                  </span>
                </div>
                <h3 className="mt-3 text-sm font-medium">{step.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {step.description}
                </p>
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
