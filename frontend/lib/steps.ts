import type { StepDef, VideoFormat } from "./types"

/**
 * The real pipeline steps emitted by the FastAPI backend, in execution order.
 * `id` matches the backend's `current_step` / `steps_completed` values exactly
 * (see backend/pipeline/orchestrator.py). `label` is the human-facing status
 * shown in the live progress card.
 */
export interface BackendStep {
  id: string
  label: string
}

export const BACKEND_STEPS: BackendStep[] = [
  { id: "github_reader", label: "Analyzing repository structure" },
  { id: "app_browser", label: "Navigating deployed site" },
  { id: "script_writer", label: "Writing narration script" },
  { id: "image_generator", label: "Designing title card" },
  { id: "voice_generator", label: "Generating AI voiceover" },
  { id: "video_assembler", label: "Assembling video, music & subtitles" },
  { id: "storage", label: "Uploading & finalizing" },
]

export const STEP_DEFS: StepDef[] = [
  {
    id: "ingest",
    title: "Ingest repository",
    description: "Clone metadata, read README, package manifest, and file tree.",
    provider: "GitHub",
    duration: 2200,
  },
  {
    id: "analyze",
    title: "Analyze project",
    description: "Detect stack, entry points, and the story worth telling.",
    provider: "GMI Cloud",
    duration: 3200,
  },
  {
    id: "script",
    title: "Write narration script",
    description: "Generate a tight 3-minute walkthrough script with scene beats.",
    provider: "GMI Cloud",
    duration: 3600,
  },
  {
    id: "voiceover",
    title: "Synthesize voiceover",
    description: "Render natural narration audio from the script.",
    provider: "ElevenLabs",
    duration: 3000,
  },
  {
    id: "capture",
    title: "Capture app walkthrough",
    description: "Drive the live deployment and record key UI flows as frames.",
    provider: "Devfields",
    duration: 3400,
  },
  {
    id: "compose",
    title: "Compose demo video",
    description: "Align scenes to narration, add captions, and render the cut.",
    provider: "Devfields",
    duration: 4200,
  },
  {
    id: "publish",
    title: "Publish + sign assets",
    description: "Upload every artifact to Backblaze B2 with a provenance manifest.",
    provider: "Backblaze B2",
    duration: 2400,
  },
]

/** Optional step, inserted before compose only when a presenter cam is requested. */
export const PRESENTER_STEP: StepDef = {
  id: "presenter",
  title: "Animate presenter",
  description: "Turn the uploaded photo into a lip-synced talking head, timed to the voiceover.",
  provider: "Devfields",
  duration: 3000,
}

const ALL_STEP_DEFS: StepDef[] = [...STEP_DEFS, PRESENTER_STEP]

/** Lookup so any consumer can resolve a step definition by id regardless of order. */
export const STEP_DEF_BY_ID: Record<string, StepDef> = Object.fromEntries(
  ALL_STEP_DEFS.map((d) => [d.id, d]),
)

/** Build the ordered pipeline for a given set of options. */
export function buildPipeline(opts: { presenter: boolean }): StepDef[] {
  const steps = [...STEP_DEFS]
  if (opts.presenter) {
    const idx = steps.findIndex((s) => s.id === "compose")
    steps.splice(idx, 0, PRESENTER_STEP)
  }
  return steps
}

export function logsFor(
  repoName: string,
  appHost: string,
  opts?: { format?: VideoFormat; durationSec?: number; presenterName?: string },
): Record<string, string[]> {
  const dur = opts?.durationSec ?? 178
  const mmss = `${Math.floor(dur / 60)}m${String(dur % 60).padStart(2, "0")}s`
  const pitch = opts?.format === "pitch_demo"
  return {
    ingest: [
      `git: resolving ${repoName}`,
      "reading README.md, package.json, app/",
      "found 142 files across 18 directories",
      "primary language: TypeScript (Next.js)",
    ],
    analyze: [
      "embedding source tree for retrieval",
      "detected: Next.js App Router, Tailwind, API routes",
      "identifying hero feature + 3 supporting flows",
      `reasoning: pacing a natural ${mmss} ${pitch ? "pitch + demo" : "demo"}`,
    ],
    script: [
      "prompt → GMI Cloud (llama-3.3-70b)",
      pitch ? "scene 1: the pitch — problem + market" : "scene 1: the problem",
      pitch ? "scene 2: the product, live" : "scene 2: live walkthrough",
      "scene 3: under the hood + close",
      `script: paced to fit ${mmss} (human delivery)`,
    ],
    voiceover: [
      "sending script to ElevenLabs",
      "voice: Devfields Narrator",
      "rendering 174s of audio @ 44.1kHz",
      "normalizing loudness to -16 LUFS",
    ],
    capture: [
      `launching headless browser → ${appHost}`,
      "replaying scripted scene actions per beat",
      "recording viewport, paced to narration length",
      "captured scenes @ 1080p (synced to audio)",
    ],
    presenter: [
      opts?.presenterName ? `loading presenter: ${opts.presenterName}` : "loading presenter photo",
      "generating talking-head frames",
      "lip-syncing avatar to voiceover phonemes",
      "rendering picture-in-picture cam (bottom-right)",
    ],
    compose: [
      "muxing each scene's audio + capture clip",
      "burning in captions + lower-thirds",
      `rendering 1080p / h.264 → ${mmss}`,
      `final cut: ${mmss}`,
    ],
    publish: [
      "uploading video.mp4 → b2://devfields",
      "uploading audio.mp3, script.json, frames/",
      "writing provenance.json (sha-256 per asset)",
      "all assets durable on Backblaze B2",
    ],
  }
}
