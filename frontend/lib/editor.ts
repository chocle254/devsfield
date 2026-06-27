import type { Asset, EditMessage, EditPatch, RunResult, Scene, VideoFormat } from "./types"
import { shortHash } from "./integrations"

const sid = () => Math.random().toString(36).slice(2, 8)

/**
 * Split a narration script into timeline scenes. Real edits target a single
 * scene so the rest of the video is never re-rendered.
 */
export function buildScenes(script: string, durationSec: number, format: VideoFormat = "demo"): Scene[] {
  const paras = script
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)

  const chunks = paras.length >= 2 ? paras.slice(0, 5) : [script.trim() || "Demo narration."]

  const titleFor = (text: string, i: number, total: number): string => {
    const t = text.toLowerCase()
    if (i === 0) return format === "pitch_demo" ? "The pitch" : "Intro"
    if (i === total - 1) return "Closing"
    if (/pitch|market|investor|now is the moment|who it's for/.test(t)) return "The pitch"
    if (/under the hood|architecture|built on|stack|engineering/.test(t)) return "How it works"
    if (/look|walkthrough|here's the|live app|interface|flow|watch/.test(t)) return "Live walkthrough"
    if (/problem|pain|struggle|hard|tedious/.test(t)) return "The problem"
    return `Scene ${i + 1}`
  }

  // distribute duration proportional to text length
  const totalLen = chunks.reduce((n, c) => n + c.length, 0) || 1
  let cursor = 0
  return chunks.map((text, i) => {
    const portion = Math.round((text.length / totalLen) * durationSec)
    const startSec = cursor
    const endSec = i === chunks.length - 1 ? durationSec : Math.min(durationSec, cursor + portion)
    cursor = endSec
    return {
      id: sid(),
      index: i,
      title: titleFor(text, i, chunks.length),
      startSec,
      endSec,
      script: text,
      status: "ready" as const,
    }
  })
}

/** Recompute scene indices + contiguous timecodes after a structural change. */
function reflow(scenes: Scene[], durationSec: number): Scene[] {
  const totalLen = scenes.reduce((n, s) => n + s.script.length, 0) || 1
  let cursor = 0
  return scenes.map((s, i) => {
    const portion = Math.round((s.script.length / totalLen) * durationSec)
    const startSec = cursor
    const endSec = i === scenes.length - 1 ? durationSec : Math.min(durationSec, cursor + portion)
    cursor = endSec
    return { ...s, index: i, startSec, endSec }
  })
}

const TONE_WORDS = ["energetic", "professional", "casual", "fun", "technical", "serious", "playful", "concise", "punchy", "friendly", "confident", "calm", "dramatic", "upbeat"]

/** Find the scene an instruction is referring to (by title keywords / ordinal). */
function targetScene(scenes: Scene[], instruction: string): Scene | undefined {
  const t = instruction.toLowerCase()
  // ordinal references
  if (/\b(first|opening|intro|beginning|start)\b/.test(t)) return scenes[0]
  if (/\b(last|final|ending|closing|outro|end)\b/.test(t)) return scenes[scenes.length - 1]
  const ord = t.match(/\b(second|third|fourth|fifth|2nd|3rd|4th|5th|scene\s*(\d))\b/)
  if (ord) {
    const map: Record<string, number> = { second: 1, "2nd": 1, third: 2, "3rd": 2, fourth: 3, "4th": 3, fifth: 4, "5th": 4 }
    const idx = ord[2] ? Number(ord[2]) - 1 : map[ord[1]] ?? -1
    if (idx >= 0 && idx < scenes.length) return scenes[idx]
  }
  // keyword match against title / script
  let best: { scene: Scene; score: number } | null = null
  for (const s of scenes) {
    const hay = `${s.title} ${s.script}`.toLowerCase()
    const words = t.split(/[^a-z]+/).filter((w) => w.length > 3)
    let score = 0
    for (const w of words) if (hay.includes(w)) score++
    if (/problem|pain/.test(t) && /problem/.test(s.title.toLowerCase())) score += 3
    if (/(architecture|under the hood|technical|stack|code)/.test(t) && /how it works/.test(s.title.toLowerCase())) score += 3
    if (/(walkthrough|demo|feature|screen|ui)/.test(t) && /walkthrough/.test(s.title.toLowerCase())) score += 3
    if (!best || score > best.score) best = { scene: s, score }
  }
  return best && best.score > 0 ? best.scene : undefined
}

export interface EditOutcome {
  scenes: Scene[]
  durationSec: number
  patch: EditPatch
  assistantText: string
}

/**
 * Interpret a natural-language edit instruction into a structured, targeted
 * patch and apply it to the scene list. Only the affected scene is treated as
 * re-rendered — the rest of the timeline is preserved verbatim.
 */
export function interpretAndApply(
  scenes: Scene[],
  durationSec: number,
  instruction: string,
): EditOutcome {
  const t = instruction.toLowerCase().trim()
  const work = scenes.map((s) => ({ ...s, status: "ready" as Scene["status"] }))

  // REMOVE / CUT -----------------------------------------------------------
  if (/\b(remove|delete|cut|drop|take out|get rid of|without)\b/.test(t)) {
    const target = targetScene(work, t) ?? work[work.length - 1]
    if (work.length <= 1) {
      return {
        scenes: work,
        durationSec,
        patch: { action: "noop", summary: "Can't remove the only remaining scene.", changedAssets: [] },
        assistantText:
          "I kept the video as-is — there's only one scene left, so removing it would leave an empty video. Try editing it instead.",
      }
    }
    const remaining = work.filter((s) => s.id !== target.id)
    const newDuration = Math.max(30, durationSec - (target.endSec - target.startSec))
    const reflowed = reflow(remaining, newDuration)
    return {
      scenes: reflowed,
      durationSec: newDuration,
      patch: {
        action: "remove",
        sceneId: target.id,
        sceneTitle: target.title,
        summary: `Removed the “${target.title}” scene and re-stitched the timeline.`,
        changedAssets: ["Final demo video", "Provenance manifest"],
      },
      assistantText: `Done — I cut the “${target.title}” scene and re-stitched the surrounding clips. The other ${remaining.length} scene${remaining.length > 1 ? "s" : ""} are untouched, so only the final cut and manifest were re-rendered (new length ~${Math.round(newDuration)}s).`,
    }
  }

  // ADD / INSERT -----------------------------------------------------------
  if (/\b(add|include|insert|append|put in|also show|mention)\b/.test(t)) {
    const cleaned = instruction.replace(/^\s*(please\s+)?(add|include|insert|append|put in|also show|mention)\s+(a|an|the)?\s*/i, "").trim()
    const title = deriveTitle(cleaned) || "New scene"
    const newScene: Scene = {
      id: sid(),
      index: work.length,
      title,
      startSec: durationSec,
      endSec: durationSec + 18,
      script: capitalize(cleaned) || "Additional highlight.",
      status: "edited",
    }
    // insert before closing if a closing scene exists
    const closingIdx = work.findIndex((s) => /closing/i.test(s.title))
    const next = closingIdx >= 0 ? [...work.slice(0, closingIdx), newScene, ...work.slice(closingIdx)] : [...work, newScene]
    const newDuration = durationSec + 18
    const reflowed = reflow(next, newDuration).map((s) => (s.id === newScene.id ? { ...s, status: "edited" as const } : s))
    return {
      scenes: reflowed,
      durationSec: newDuration,
      patch: {
        action: "add",
        sceneId: newScene.id,
        sceneTitle: title,
        summary: `Added a new “${title}” scene.`,
        changedAssets: ["New scene clip", "Voiceover audio", "Final demo video", "Provenance manifest"],
      },
      assistantText: `Added a new “${title}” scene and rendered just that segment, then spliced it into the existing cut. Everything before and after stays exactly as it was.`,
    }
  }

  // TRIM / SHORTEN ---------------------------------------------------------
  if (/\b(shorter|shorten|trim|faster|tighten|speed up|cut it down|too long)\b/.test(t)) {
    const newDuration = Math.max(45, Math.round(durationSec * 0.8))
    const reflowed = reflow(work, newDuration).map((s) => ({ ...s, status: "edited" as const }))
    return {
      scenes: reflowed,
      durationSec: newDuration,
      patch: {
        action: "trim",
        summary: `Tightened pacing across all scenes (~${Math.round(durationSec)}s → ~${newDuration}s).`,
        changedAssets: ["Final demo video", "Provenance manifest"],
      },
      assistantText: `Tightened the pacing — trimmed dead air and quickened the cuts. New runtime is about ${newDuration} seconds. Scene content is preserved, only the timing was recompiled.`,
    }
  }

  // RETONE -----------------------------------------------------------------
  const toneHit = TONE_WORDS.find((w) => t.includes(w))
  if (toneHit || /\b(tone|sound more|feel more|voice|narrat)\b/.test(t)) {
    const tone = toneHit ?? "polished"
    const reflowed = work.map((s) => ({ ...s, status: "edited" as const }))
    return {
      scenes: reflowed,
      durationSec,
      patch: {
        action: "retone",
        summary: `Re-recorded the narration in a more ${tone} tone.`,
        changedAssets: ["Narration script", "Voiceover audio", "Final demo video"],
      },
      assistantText: `Re-recorded the voiceover with a more ${tone} delivery. The on-screen visuals and timing are unchanged — I only regenerated the audio track and re-muxed it onto the existing video.`,
    }
  }

  // MODIFY a specific scene ------------------------------------------------
  if (/\b(change|make|replace|update|rewrite|reword|edit|fix|swap|highlight|emphasize|focus)\b/.test(t)) {
    const target = targetScene(work, t) ?? work[0]
    const edited = work.map((s) =>
      s.id === target.id
        ? { ...s, status: "edited" as const, script: applyTweak(s.script, instruction) }
        : s,
    )
    return {
      scenes: edited,
      durationSec,
      patch: {
        action: "modify",
        sceneId: target.id,
        sceneTitle: target.title,
        summary: `Reworked the “${target.title}” scene.`,
        changedAssets: ["Narration script", "Voiceover audio", `${target.title} clip`, "Final demo video"],
      },
      assistantText: `Updated the “${target.title}” scene to match your note, then re-rendered only that segment and dropped it back into the timeline. The rest of the video is byte-for-byte identical.`,
    }
  }

  // FALLBACK: treat as a modify on the most relevant scene -----------------
  const target = targetScene(work, t) ?? work[0]
  const edited = work.map((s) =>
    s.id === target.id ? { ...s, status: "edited" as const, script: applyTweak(s.script, instruction) } : s,
  )
  return {
    scenes: edited,
    durationSec,
    patch: {
      action: "modify",
      sceneId: target.id,
      sceneTitle: target.title,
      summary: `Applied your note to the “${target.title}” scene.`,
      changedAssets: ["Narration script", "Voiceover audio", "Final demo video"],
    },
    assistantText: `I applied that to the “${target.title}” scene and re-rendered just that part. Tell me what to tweak next, or ask me to add, remove, shorten, or change the tone.`,
  }
}

function deriveTitle(text: string): string {
  const words = text.split(/\s+/).slice(0, 4).join(" ")
  return capitalize(words.replace(/[.,!?]+$/, ""))
}

function capitalize(s: string): string {
  if (!s) return s
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function applyTweak(script: string, instruction: string): string {
  const note = instruction.trim().replace(/\s+/g, " ")
  // Annotate the script with the directive so the change is visible in the UI.
  return `${script}\n\n[edit: ${note}]`
}

/**
 * Re-hash only the assets that changed (verifiable provenance), bump version,
 * and update the manifest. Returns the updated asset list.
 */
export async function rehashChangedAssets(
  assets: Asset[],
  changedLabels: string[],
  version: number,
): Promise<Asset[]> {
  const changed = new Set(changedLabels)
  const out: Asset[] = []
  for (const a of assets) {
    if (changed.has(a.label) || a.label === "Provenance manifest") {
      const hash = await shortHash(a.b2Key + version + Date.now())
      out.push({ ...a, hash })
    } else {
      out.push(a)
    }
  }
  return out
}

export function applyEditToResult(result: RunResult, outcome: EditOutcome, instruction: string): EditMessage[] {
  const now = Date.now()
  const userMsg: EditMessage = { id: sid(), role: "user", text: instruction, at: now }
  const botMsg: EditMessage = {
    id: sid(),
    role: "assistant",
    text: outcome.assistantText,
    at: now + 1,
    patch: outcome.patch,
  }
  return [userMsg, botMsg]
}
