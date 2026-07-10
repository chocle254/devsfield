import type { StepDef } from "./types"

/**
 * The 7 pipeline steps, matching the backend orchestrator exactly.
 * `id` maps 1:1 to the step keys the backend emits over SSE
 * (`current_step` / `steps_completed`).
 */
export const STEP_DEFS: StepDef[] = [
  {
    id: "github_reader",
    title: "Read the repo",
    description: "Fetch the README, file tree, framework, and key source files via the GitHub API.",
    provider: "GitHub",
  },
  {
    id: "app_browser",
    title: "Navigate the live app",
    description:
      "An AI-guided headless browser reads the accessibility tree and decides what to click, recording real features.",
    provider: "GMI Cloud",
  },
  {
    id: "script_writer",
    title: "Write the narration",
    description: "Generate one narration line per navigation segment, synced to what's on screen.",
    provider: "GMI Cloud",
  },
  {
    id: "image_generator",
    title: "Generate title card",
    description: "Create a branded AI title-card image for the video open.",
    provider: "GMI Cloud",
  },
  {
    id: "voice_generator",
    title: "Generate the voiceover",
    description: "Synthesize one ElevenLabs voice clip per segment via Genblaze.",
    provider: "ElevenLabs",
  },
  {
    id: "video_assembler",
    title: "Composite the video",
    description: "FFmpeg pads each clip to its voiceover, merges audio, and concatenates the final MP4.",
    provider: "Devfields",
  },
  {
    id: "storage",
    title: "Upload to Backblaze B2",
    description: "Store the final video, every segment, the segment manifest, and a SHA-256 provenance manifest.",
    provider: "Backblaze B2",
  },
]

/** Lookup so any consumer can resolve a step definition by its backend id. */
export const STEP_DEF_BY_ID: Record<string, StepDef> = Object.fromEntries(
  STEP_DEFS.map((d) => [d.id, d]),
)
