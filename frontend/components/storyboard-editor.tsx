"use client"

// Lets a developer script the demo exactly instead of letting the AI guess
// what to click. Shape mirrors backend/models.py's StoryboardBeat /
// StoryboardStep so onSubmit in url-input-form.tsx can forward it as-is.

export type StepAction = "click" | "type" | "select" | "toggle" | "press" | "scroll"

export interface StoryboardStepDraft {
  action: StepAction
  target: string
  value: string
  expected_result: string
}

export interface StoryboardBeatDraft {
  route: string
  feature: string
  talking_point: string
  seconds: string
  interaction_steps: StoryboardStepDraft[]
}

const ACTIONS: { value: StepAction; label: string; needsValue: boolean }[] = [
  { value: "click", label: "Click", needsValue: false },
  { value: "type", label: "Type", needsValue: true },
  { value: "select", label: "Select", needsValue: true },
  { value: "toggle", label: "Toggle", needsValue: false },
  { value: "press", label: "Press key", needsValue: true },
  { value: "scroll", label: "Scroll to", needsValue: false },
]

export function emptyStep(): StoryboardStepDraft {
  return { action: "click", target: "", value: "", expected_result: "" }
}

export function emptyBeat(): StoryboardBeatDraft {
  return { route: "/", feature: "", talking_point: "", seconds: "", interaction_steps: [] }
}

interface StoryboardEditorProps {
  beats: StoryboardBeatDraft[]
  onChange: (beats: StoryboardBeatDraft[]) => void
  disabled?: boolean
}

export function StoryboardEditor({ beats, onChange, disabled }: StoryboardEditorProps) {
  function updateBeat(index: number, patch: Partial<StoryboardBeatDraft>) {
    onChange(beats.map((b, i) => (i === index ? { ...b, ...patch } : b)))
  }

  function removeBeat(index: number) {
    onChange(beats.filter((_, i) => i !== index))
  }

  function addBeat() {
    onChange([...beats, emptyBeat()])
  }

  function updateStep(beatIndex: number, stepIndex: number, patch: Partial<StoryboardStepDraft>) {
    const beat = beats[beatIndex]
    const steps = beat.interaction_steps.map((s, i) => (i === stepIndex ? { ...s, ...patch } : s))
    updateBeat(beatIndex, { interaction_steps: steps })
  }

  function removeStep(beatIndex: number, stepIndex: number) {
    const beat = beats[beatIndex]
    updateBeat(beatIndex, { interaction_steps: beat.interaction_steps.filter((_, i) => i !== stepIndex) })
  }

  function addStep(beatIndex: number) {
    const beat = beats[beatIndex]
    updateBeat(beatIndex, { interaction_steps: [...beat.interaction_steps, emptyStep()] })
  }

  return (
    <div className="space-y-3">
      {beats.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
          No scenes yet. Add one to start scripting exactly what the AI should show.
        </p>
      ) : null}

      {beats.map((beat, beatIndex) => (
        <div key={beatIndex} className="rounded-lg border border-border bg-secondary/40 p-3.5">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Scene {beatIndex + 1}
            </span>
            <button
              type="button"
              disabled={disabled}
              onClick={() => removeBeat(beatIndex)}
              className="text-xs font-medium text-destructive hover:underline disabled:opacity-60"
            >
              Remove scene
            </button>
          </div>

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-[1fr_auto]">
            <MiniField
              label="Page path"
              value={beat.route}
              onChange={(v) => updateBeat(beatIndex, { route: v })}
              placeholder="/dashboard"
              disabled={disabled}
            />
            <div className="sm:w-28">
              <MiniField
                label="Seconds (optional)"
                value={beat.seconds}
                onChange={(v) => updateBeat(beatIndex, { seconds: v.replace(/[^0-9]/g, "") })}
                placeholder="20"
                disabled={disabled}
              />
            </div>
          </div>

          <div className="mt-2.5">
            <MiniField
              label="What the narration should say"
              value={beat.talking_point}
              onChange={(v) => updateBeat(beatIndex, { talking_point: v })}
              placeholder="This is where users see their weekly summary."
              disabled={disabled}
            />
          </div>

          {/* Interaction steps */}
          <div className="mt-3 space-y-2">
            {beat.interaction_steps.map((step, stepIndex) => {
              const meta = ACTIONS.find((a) => a.value === step.action) ?? ACTIONS[0]
              return (
                <div
                  key={stepIndex}
                  className="grid grid-cols-1 gap-1.5 rounded-md border border-border bg-card p-2 sm:grid-cols-[100px_1fr_1fr_1fr_auto] sm:items-center"
                >
                  <select
                    value={step.action}
                    disabled={disabled}
                    onChange={(e) => updateStep(beatIndex, stepIndex, { action: e.target.value as StepAction })}
                    className="rounded-md border border-border bg-card px-2 py-1.5 text-xs text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-ring disabled:opacity-60"
                  >
                    {ACTIONS.map((a) => (
                      <option key={a.value} value={a.value}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                  <TinyInput
                    value={step.target}
                    onChange={(v) => updateStep(beatIndex, stepIndex, { target: v })}
                    placeholder='Button/field label, e.g. "Add task"'
                    disabled={disabled}
                  />
                  <TinyInput
                    value={step.value}
                    onChange={(v) => updateStep(beatIndex, stepIndex, { value: v })}
                    placeholder={meta.needsValue ? 'Text to type, e.g. "Plan launch"' : "—"}
                    disabled={disabled || !meta.needsValue}
                  />
                  <TinyInput
                    value={step.expected_result}
                    onChange={(v) => updateStep(beatIndex, stepIndex, { expected_result: v })}
                    placeholder="What should appear after (optional)"
                    disabled={disabled}
                  />
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => removeStep(beatIndex, stepIndex)}
                    aria-label="Remove step"
                    className="justify-self-end rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-destructive disabled:opacity-60"
                  >
                    <TrashIcon />
                  </button>
                </div>
              )
            })}
            <button
              type="button"
              disabled={disabled}
              onClick={() => addStep(beatIndex)}
              className="text-xs font-medium text-primary hover:underline disabled:opacity-60"
            >
              + Add step
            </button>
          </div>
        </div>
      ))}

      <button
        type="button"
        disabled={disabled}
        onClick={addBeat}
        className="w-full rounded-lg border border-dashed border-border py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-60"
      >
        + Add scene
      </button>
    </div>
  )
}

function MiniField({
  label,
  value,
  onChange,
  placeholder,
  disabled,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  disabled?: boolean
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium text-muted-foreground">{label}</span>
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-ring disabled:opacity-60"
      />
    </label>
  )
}

function TinyInput({
  value,
  onChange,
  placeholder,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  disabled?: boolean
}) {
  return (
    <input
      type="text"
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-primary focus:ring-1 focus:ring-ring disabled:opacity-60 disabled:bg-secondary/40"
    />
  )
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6h16Z" />
    </svg>
  )
}
