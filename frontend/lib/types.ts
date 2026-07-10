// Types mirror the FastAPI backend contract described in the README.

/** Video tone/format chosen in the form. Mapped to the backend `tone` field. */
export type VideoFormat = "demo" | "pitch_demo"

export type Provider = "GitHub" | "GMI Cloud" | "ElevenLabs" | "Backblaze B2" | "Devfields"

/** A pipeline step id — matches the backend orchestrator's step keys. */
export type StepId =
  | "github_reader"
  | "app_browser"
  | "script_writer"
  | "image_generator"
  | "voice_generator"
  | "video_assembler"
  | "storage"

export interface StepDef {
  id: StepId
  title: string
  description: string
  provider: Provider
}

/** Display status derived from the backend's current_step / steps_completed. */
export type StepStatus = "pending" | "active" | "done"

/** Job lifecycle status emitted by the backend. */
export type JobStatus = "queued" | "in_progress" | "complete" | "failed"

/** Raw event shape streamed from the backend `/stream/{id}` endpoint (via our proxy). */
export interface StreamEvent {
  job_id?: string
  status?: JobStatus
  current_step?: StepId | null
  steps_completed?: StepId[]
  message?: string | null
  error?: string | null
  video_url?: string | null
}

/** One recorded segment stored individually on Backblaze B2. */
export interface Segment {
  segment_id: string
  clip_key: string
  clip_url: string
  voice_key: string
  voice_url: string
}

/** Normalized result returned by our `/api/result/{id}` proxy. */
export interface RunResult {
  videoUrl: string
  manifestUrl?: string
  segmentsUrl?: string
  segments?: Segment[]
  sha256?: string
  modelsUsed?: Record<string, string>
  generatedAt?: string
}
