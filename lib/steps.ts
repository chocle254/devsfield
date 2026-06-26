import type { StepDef } from "./types"

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

export function logsFor(repoName: string, appHost: string): Record<string, string[]> {
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
      "drafting narrative arc",
    ],
    script: [
      "prompt → GMI Cloud (llama-3.3-70b)",
      "scene 1: the problem",
      "scene 2: live walkthrough",
      "scene 3: under the hood + close",
      "script: 412 words / ~2m54s read",
    ],
    voiceover: [
      "sending script to ElevenLabs",
      "voice: Devfields Narrator",
      "rendering 174s of audio @ 44.1kHz",
      "normalizing loudness to -16 LUFS",
    ],
    capture: [
      `launching headless browser → ${appHost}`,
      "recording: landing → input → run",
      "recording: live pipeline → result",
      "captured 6 scenes / 1080p",
    ],
    compose: [
      "aligning scenes to narration timestamps",
      "burning in captions + lower-thirds",
      "rendering 1080p / h.264",
      "final cut: 2m58s",
    ],
    publish: [
      "uploading video.mp4 → b2://devfields",
      "uploading audio.mp3, script.json, frames/",
      "writing provenance.json (sha-256 per asset)",
      "all assets durable on Backblaze B2",
    ],
  }
}
