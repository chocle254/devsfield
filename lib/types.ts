export type StepId =
  | "ingest"
  | "analyze"
  | "script"
  | "voiceover"
  | "capture"
  | "compose"
  | "publish"

export type StepStatus = "pending" | "active" | "done" | "error"

export type Provider = "GitHub" | "GMI Cloud" | "ElevenLabs" | "Backblaze B2" | "Devfields"

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

export interface RunResult {
  videoUrl: string
  posterUrl: string
  durationSec: number
  title: string
  summary: string
  scriptPreview: string
  assets: Asset[]
}

export interface RunRecord {
  id: string
  repoUrl: string
  appUrl: string
  createdAt: number
  status: "running" | "done" | "error"
  steps: StepState[]
  result?: RunResult
  error?: string
}

export interface RunInput {
  repoUrl: string
  appUrl: string
}
