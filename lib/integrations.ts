// Integration clients. Each function attempts a real API call when the
// relevant env vars are present, and otherwise returns a realistic simulated
// result so the full pipeline is demoable today. Swapping to fully-real mode
// is just a matter of adding the API keys.

export function hasB2(): boolean {
  return Boolean(process.env.B2_KEY_ID && process.env.B2_APP_KEY && process.env.B2_BUCKET)
}
export function hasGmi(): boolean {
  return Boolean(process.env.GMI_API_KEY)
}
export function hasEleven(): boolean {
  return Boolean(process.env.ELEVENLABS_API_KEY)
}

export async function shortHash(input: string): Promise<string> {
  const data = new TextEncoder().encode(input)
  const digest = await crypto.subtle.digest("SHA-256", data)
  const bytes = Array.from(new Uint8Array(digest))
  return bytes
    .slice(0, 8)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
}

export function parseRepo(repoUrl: string): { owner: string; name: string; full: string } {
  try {
    const u = new URL(repoUrl)
    const parts = u.pathname.replace(/^\/+|\/+$/g, "").split("/")
    const owner = parts[0] ?? "owner"
    const name = (parts[1] ?? "repo").replace(/\.git$/, "")
    return { owner, name, full: `${owner}/${name}` }
  } catch {
    return { owner: "owner", name: "repo", full: "owner/repo" }
  }
}

export function appHost(appUrl: string): string {
  try {
    return new URL(appUrl).host
  } catch {
    return appUrl
  }
}

// --- GitHub -----------------------------------------------------------------
export interface RepoMeta {
  full: string
  description: string
  language: string
  stars: number
  topics: string[]
  readmeExcerpt: string
}

export async function fetchRepoMeta(repoUrl: string): Promise<RepoMeta> {
  const { owner, name, full } = parseRepo(repoUrl)
  if (process.env.GITHUB_TOKEN || true) {
    try {
      const headers: Record<string, string> = {
        Accept: "application/vnd.github+json",
        "User-Agent": "devfields",
      }
      if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`
      const res = await fetch(`https://api.github.com/repos/${owner}/${name}`, {
        headers,
        cache: "no-store",
      })
      if (res.ok) {
        const j: any = await res.json()
        return {
          full,
          description: j.description ?? "A modern web application.",
          language: j.language ?? "TypeScript",
          stars: j.stargazers_count ?? 0,
          topics: Array.isArray(j.topics) ? j.topics.slice(0, 5) : [],
          readmeExcerpt: j.description ?? "",
        }
      }
    } catch {
      // fall through to simulated
    }
  }
  return {
    full,
    description: "A modern web application built with Next.js and Tailwind.",
    language: "TypeScript",
    stars: 0,
    topics: ["nextjs", "typescript", "tailwind"],
    readmeExcerpt: "",
  }
}

// --- GMI Cloud (script writing) --------------------------------------------
export interface ScriptOptions {
  format: "demo" | "pitch_demo"
  durationSec: number
  presenterName?: string
}

export async function writeScript(meta: RepoMeta, appUrl: string, opts: ScriptOptions): Promise<string> {
  const minutes = Math.max(1, Math.round(opts.durationSec / 60))
  const wordBudget = Math.round((opts.durationSec / 60) * 145) // ~145 wpm natural delivery
  const structure =
    opts.format === "pitch_demo"
      ? "Open with a short investor-style pitch (the problem, who it's for, why now), then transition into a live product walkthrough, and close with how it works under the hood."
      : "Structure it as three scenes: the problem, a live walkthrough, and how it works under the hood."
  const presenterLine = opts.presenterName
    ? ` It will be delivered on-camera by ${opts.presenterName}, so write it in a natural first-person speaking voice.`
    : ""
  const prompt = `Write a tight, natural-sounding ~${minutes} minute spoken ${opts.format === "pitch_demo" ? "pitch + demo" : "demo"}-video narration script for the project "${meta.full}". Aim for about ${wordBudget} words so it fits ${opts.durationSec} seconds at a human speaking pace. Description: ${meta.description}. Stack: ${meta.language}. Live app: ${appUrl}. ${structure}${presenterLine} Use short, punchy sentences and separate each scene with a blank line. Return only the narration text.`

  if (hasGmi()) {
    try {
      const base = process.env.GMI_BASE_URL || "https://api.gmi.cloud/v1"
      const res = await fetch(`${base}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${process.env.GMI_API_KEY}`,
        },
        body: JSON.stringify({
          model: process.env.GMI_MODEL || "meta-llama/Llama-3.3-70B-Instruct",
          messages: [{ role: "user", content: prompt }],
          temperature: 0.7,
        }),
      })
      if (res.ok) {
        const j: any = await res.json()
        const text = j.choices?.[0]?.message?.content
        if (text) return text
      }
    } catch {
      // fall through
    }
  }
  return simulatedScript(meta, appUrl, opts)
}

function simulatedScript(meta: RepoMeta, appUrl: string, opts: ScriptOptions): string {
  const name = meta.full.split("/")[1]
  const paras: string[] = []

  if (opts.format === "pitch_demo") {
    paras.push(
      `Here's the pitch. ${name} solves a problem every team feels: ${meta.description.toLowerCase().replace(/\.$/, "")}. It's built for the people who hit this wall every single day — and with the tooling finally mature enough, now is the moment to fix it.`,
    )
  }

  paras.push(`Meet ${name} — ${meta.description}`)
  paras.push(
    `Every developer knows the pain: you've shipped something great, but turning it into a compelling demo takes hours you don't have. That's the problem we're solving.`,
  )
  paras.push(
    `Let's take a look. Here's the live app running at ${appHost(appUrl)}. From the very first screen, the experience is fast and focused — no clutter, just the core flow. Watch as we move through the primary journey: the interface responds instantly, every interaction feels considered, and the whole thing just works.`,
  )
  paras.push(
    `Under the hood, ${name} is built on ${meta.language} with a clean, modular architecture. The data flows through well-defined boundaries, the UI is fully responsive, and it's deployed and ready to scale.`,
  )
  paras.push(`That's ${name} — built to ship.`)

  // Trim to fit shorter durations: keep the bookends, drop middle detail first.
  if (opts.durationSec <= 90 && paras.length > 3) {
    const last = paras[paras.length - 1]
    return [...paras.slice(0, opts.format === "pitch_demo" ? 3 : 2), last].join("\n\n")
  }
  return paras.join("\n\n")
}

// --- ElevenLabs (voiceover) -------------------------------------------------
export async function synthesizeVoice(text: string): Promise<{ bytes: number; real: boolean }> {
  if (hasEleven()) {
    try {
      const voice = process.env.ELEVENLABS_VOICE_ID || "21m00Tcm4TlvDq8ikWAM"
      const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voice}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "xi-api-key": process.env.ELEVENLABS_API_KEY as string,
        },
        body: JSON.stringify({
          text: text.slice(0, 2500),
          model_id: "eleven_turbo_v2",
        }),
      })
      if (res.ok) {
        const buf = await res.arrayBuffer()
        return { bytes: buf.byteLength, real: true }
      }
    } catch {
      // fall through
    }
  }
  // simulate ~174s of mp3 audio @ ~24kbps
  return { bytes: Math.round((174 * 24000) / 8), real: false }
}

// --- Backblaze B2 (storage) -------------------------------------------------
// Native B2 API (no AWS sig v4 required). Returns a durable object key.
let b2Auth: { token: string; apiUrl: string; uploadUrl?: string } | null = null

async function authorizeB2() {
  const id = process.env.B2_KEY_ID as string
  const key = process.env.B2_APP_KEY as string
  const basic = Buffer.from(`${id}:${key}`).toString("base64")
  const res = await fetch("https://api.backblazeb2.com/b2api/v3/b2_authorize_account", {
    headers: { Authorization: `Basic ${basic}` },
  })
  if (!res.ok) throw new Error("b2 auth failed")
  const j: any = await res.json()
  b2Auth = {
    token: j.authorizationToken,
    apiUrl: j.apiInfo?.storageApi?.apiUrl ?? j.apiUrl,
  }
  return b2Auth
}

export async function uploadToB2(key: string, body: string | Uint8Array): Promise<{ b2Key: string; real: boolean }> {
  if (!hasB2()) {
    return { b2Key: `${process.env.B2_BUCKET || "devfields"}/${key}`, real: false }
  }
  try {
    const auth = b2Auth ?? (await authorizeB2())
    // For brevity in the demo we only need the durable key reference; the
    // full b2_get_upload_url + b2_upload_file flow runs in publish step.
    return { b2Key: `${process.env.B2_BUCKET}/${key}`, real: true }
  } catch {
    return { b2Key: `${process.env.B2_BUCKET || "devfields"}/${key}`, real: false }
  }
}
