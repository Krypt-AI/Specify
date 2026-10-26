import type { NodeTypeSpec, RunStatus } from '@/api/types'

export const RUN_STATUS: Record<RunStatus, { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' }> = {
  running: { label: 'Running', tone: 'neutral' },
  waiting: { label: 'Waiting', tone: 'warning' },
  retrying: { label: 'Retrying', tone: 'warning' },
  paused: { label: 'Paused', tone: 'neutral' },
  completed: { label: 'Completed', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
}

export const STEP_STATUS_TONE: Record<string, 'neutral' | 'success' | 'warning' | 'danger'> = {
  completed: 'success',
  simulated: 'neutral',
  skipped: 'neutral',
  waiting: 'warning',
  retrying: 'warning',
  failed: 'danger',
}

/** Outputs a step offers: its own branches plus an error path for steps that can fail. */
export function outputsOf(spec: NodeTypeSpec) {
  return spec.trigger || spec.key === 'end' ? spec.handles : [...spec.handles, 'error']
}

export const HANDLE_LABELS: Record<string, string> = { out: 'Next', true: 'Yes', false: 'No', error: 'On error' }

export function describeWait(waiting: { kind: string; message?: string } | null) {
  if (!waiting) return null
  return (
    {
      decision: 'Waiting for your decision',
      approval: 'Waiting for your approval',
      delay: 'Waiting',
      paused: 'Held by the global pause',
    }[waiting.kind] ?? 'Waiting'
  )
}
