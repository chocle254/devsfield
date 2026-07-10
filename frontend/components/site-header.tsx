import Link from "next/link"

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <Logo />
          <span className="font-mono text-sm font-semibold tracking-tight">devfields</span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <Link
            href="/docs"
            className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:text-foreground"
          >
            API Docs
          </Link>
          <a
            href="https://github.com"
            target="_blank"
            rel="noreferrer"
            className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:text-foreground"
          >
            GitHub
          </a>
          <Link
            href="/#start"
            className="rounded-md bg-primary px-3.5 py-1.5 font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Generate
          </Link>
        </nav>
      </div>
    </header>
  )
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span
      className={`flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground ${className}`}
      aria-hidden
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="6 4 18 12 6 20 6 4" />
      </svg>
    </span>
  )
}
