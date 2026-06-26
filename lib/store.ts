import type { RunRecord } from "./types"

// In-memory store for runs. Survives across requests within a single server
// instance (sufficient for the demo). Uses a global to survive HMR in dev.
const globalForStore = globalThis as unknown as {
  __devfieldsRuns?: Map<string, RunRecord>
}

const runs: Map<string, RunRecord> = globalForStore.__devfieldsRuns ?? new Map()
if (!globalForStore.__devfieldsRuns) globalForStore.__devfieldsRuns = runs

export function saveRun(run: RunRecord) {
  runs.set(run.id, run)
}

export function getRun(id: string): RunRecord | undefined {
  return runs.get(id)
}

export function newId(): string {
  return Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4)
}
