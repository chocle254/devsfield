export type StepId =
  | "ingest"
  | "analyze"
  | "script"
  | "voiceover"
  | "capture"
  | "presenter"
  | "compose"
  | "publish"

export type VideoFormat = "demo" | "pitch_demo"

export interface PresenterConfig {
  /** show a small picture-in-picture presenter (Zoom-style) */
  enabled: boolean
  name?: string
  /** uploaded photo as a data URL — animated as a talking head */
  photoUrl?: string
}

export interface DemoCredentials {
  /** demo-account email or username the AI uses to sign in during recording */
  username: string
  password: string
}

export interface VideoOptions {
  /** hard cap on the produced video length, in seconds (<= 300) */
  maxDurationSec: number
  /** demo walkthrough only, or an investor-style pitch followed by the demo */
  format: VideoFormat
  presenter: PresenterConfig
  /** optional login for apps behind authentication — used once, never stored */
  credentials?: DemoCredentials
}

export type StepStatus = "pending" | "active" | "done" | "error"

export type Provider = "GitHub" | "GMI Cloud" | "ElevenLabs" | "Backblaze B2" | "Devsfield"

export interface StepDef {
  id: StepId
  title: string
  description: string
  provider: Provider
  /** simulated duration in ms */
  duration: number
}

export interface StepState {
  id: StepId
  status: StepStatus
  startedAt?: number
  finishedAt?: number
  /** human readable log lines emitted while running */
  logs: string[]
  /** whether this step used a real API or simulated output */
  mode: "real" | "simulated"
}

export interface Asset {
  key: string
  label: string
  kind: "json" | "audio" | "image" | "video" | "text"
  size: string
  /** B2 object key (or simulated key) */
  b2Key: string
  /** sha-256 short hash for provenance */
  hash: string
  provider: Provider
  url?: string
}

export interface Scene {
  id: string
  index: number
  title: string
  startSec: number
  endSec: number
  script: string
  /** "ready" = settled, "rendering" = currently being re-generated, "edited" = recently changed */
  status: "ready" | "rendering" | "edited"
}

export type EditAction = "remove" | "add" | "modify" | "retone" | "trim" | "reorder" | "noop"

export interface EditPatch {
  action: EditAction
  /** scene the edit targeted, if any */
  sceneId?: string
  sceneTitle?: string
  /** short human summary of what changed */
  summary: string
  /** asset labels that had to be re-rendered (kept minimal on purpose) */
  changedAssets: string[]
}

export interface EditMessage {
  id: string
  role: "user" | "assistant"
  text: string
  at: number
  /** present on assistant messages that applied a change */
  patch?: EditPatch
}

export interface RunResult {
  videoUrl: string
  /** ordered per-segment clip URLs, played back-to-back in the watch view */
  clipUrls?: string[]
  posterUrl: string
  durationSec: number
  title: string
  summary: string
  scriptPreview: string
  assets: Asset[]
  /** timeline broken into scenes so edits can target a single segment */
  scenes: Scene[]
  /** bumps every time a targeted edit is applied */
  version: number
  /** chat-style edit history */
  edits: EditMessage[]
  /** video format that was produced */
  format: VideoFormat
  /** presenter overlay, present only when the user enabled it */
  presenter?: PresenterConfig
}

export interface RunRecord {
  id: string
  repoUrl: string
  appUrl: string
  createdAt: number
  status: "running" | "done" | "error"
  steps: StepState[]
  options: VideoOptions
  result?: RunResult
  error?: string
}

export interface RunInput {
  repoUrl: string
  appUrl: string
  options: VideoOptions
}
