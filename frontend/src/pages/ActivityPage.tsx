import { Activity, ArrowLeft } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'

import { useTimezone } from '@/api/account'
import type { NodeRun } from '@/api/types'
import { useActivity, useRun, useRunAction, useRuns } from '@/api/workflows'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { fieldClass } from '@/components/ui/field'
import { describeWait, RUN_STATUS, STEP_STATUS_TONE } from '@/lib/workflows'
import { cn, formatDateTime, formatShortDate } from '@/lib/utils'

export function ActivityPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'events' ? 'events' : 'runs'
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Activity</h1>
        <p className="mt-1 text-sm text-muted">Every workflow run step by step, and everything that changed.</p>
      </div>
      <nav className="flex gap-1 border-b border-border" aria-label="Activity sections">
        {(['runs', 'events'] as const).map((key) => (
          <button
            key={key}
            onClick={() => setParams({ tab: key })}
            className={cn('-mb-px border-b-2 px-3 py-2 text-sm', tab === key ? 'border-primary font-medium text-primary' : 'border-transparent text-muted')}
          >
            {key === 'runs' ? 'Workflow runs' : 'Events'}
          </button>
        ))}
      </nav>
      {tab === 'runs' ? <Runs /> : <Events />}
    </div>
  )
}

function Runs() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const selected = params.get('run')
  const { data: runs = [], isLoading } = useRuns({ status })
  const timezone = useTimezone()
  const update = (changes: Record<string, string | null>) =>
    setParams((current) => {
      const next = new URLSearchParams(current)
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      return next
    })

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <section className={cn('min-w-0 space-y-3', selected && 'hidden lg:block')}>
        <select aria-label="Status" className={cn(fieldClass, 'mt-0')} value={status} onChange={(e) => update({ status: e.target.value || null })}>
          <option value="">All runs</option>
          {Object.entries(RUN_STATUS).map(([value, info]) => (
            <option key={value} value={value}>
              {info.label}
            </option>
          ))}
        </select>
        {isLoading ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : runs.length === 0 ? (
          <EmptyState icon={Activity} title="No runs" description="Runs appear as emails arrive and workflows start." />
        ) : (
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
            {runs.map((run) => (
              <li key={run.id}>
                <button
                  onClick={() => update({ run: run.id })}
                  className={cn('block w-full px-4 py-3 text-left hover:bg-background', run.id === selected && 'bg-primary/5')}
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">{run.workflow_name}</span>
                    <span className="text-xs text-muted">{formatShortDate(run.created_at, timezone)}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Badge tone={RUN_STATUS[run.status].tone}>{RUN_STATUS[run.status].label}</Badge>
                    {run.is_test && <Badge>Test</Badge>}
                    <span className="truncate text-xs text-muted">
                      {run.status === 'waiting' ? describeWait(run.waiting_for) : run.error_message ?? run.current_node_id}
                    </span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      {selected ? (
        <RunPanel key={selected} id={selected} onClose={() => update({ run: null })} />
      ) : (
        <div className="hidden items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted lg:flex">
          Select a run to inspect its steps
        </div>
      )}
    </div>
  )
}

function RunPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: run } = useRun(id)
  const action = useRunAction()
  const timezone = useTimezone()
  if (!run) return <Card className="text-sm text-muted">Loading run…</Card>
  const act = (name: Parameters<typeof action.mutate>[0]['action']) => action.mutate({ id: run.id, action: name })
  const active = ['running', 'waiting', 'retrying'].includes(run.status)

  return (
    <Card className="min-w-0 space-y-4">
      <div className="flex items-start gap-3">
        <button onClick={onClose} className="mt-1 lg:hidden" aria-label="Back to runs">
          <ArrowLeft className="size-5" />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">{run.workflow_name}</h2>
          <p className="text-xs text-muted">
            Started {formatDateTime(run.started_at, timezone)} · {run.trigger_event_id}
          </p>
        </div>
        <Badge tone={RUN_STATUS[run.status].tone}>{RUN_STATUS[run.status].label}</Badge>
      </div>
      {run.status === 'waiting' && (
        <p className="rounded-md bg-warning/10 px-3 py-2 text-sm">
          {describeWait(run.waiting_for)}
          {run.waiting_for?.message && `: ${run.waiting_for.message}`}
          {run.waiting_for?.kind === 'decision' && run.waiting_for.opportunity_id && (
            <>
              {' '}
              <Link to={`/decisions?id=${run.waiting_for.opportunity_id}`} className="font-medium text-primary hover:underline">
                Decide now
              </Link>
            </>
          )}
        </p>
      )}
      {run.error_message && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{run.error_message}</p>}
      <div className="flex flex-wrap gap-2">
        {run.waiting_for?.kind === 'approval' && run.status === 'waiting' && (
          <>
            <Button onClick={() => act('approve')}>Approve</Button>
            <Button variant="outline" onClick={() => act('reject')}>
              Reject
            </Button>
          </>
        )}
        {run.status === 'failed' && <Button onClick={() => act('retry')}>Retry from the failed step</Button>}
        {active && (
          <Button variant="outline" onClick={() => act('pause')}>
            Pause
          </Button>
        )}
        {run.status === 'paused' && <Button onClick={() => act('resume')}>Resume</Button>}
        {(active || run.status === 'paused') && (
          <Button variant="ghost" onClick={() => window.confirm('Cancel this run?') && act('cancel')}>
            Cancel run
          </Button>
        )}
      </div>
      {action.isError && <p className="text-sm text-danger">{action.error.message}</p>}
      <ol className="space-y-2">
        {run.node_runs.map((step) => (
          <Step key={step.id} step={step} />
        ))}
      </ol>
    </Card>
  )
}

function Step({ step }: { step: NodeRun }) {
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <details>
        <summary className="flex cursor-pointer items-center gap-2">
          <Badge tone={STEP_STATUS_TONE[step.status] ?? 'neutral'}>{step.status}</Badge>
          <span className="font-medium">{step.node_id}</span>
          <span className="text-xs text-muted">{step.node_type.replaceAll('_', ' ')}</span>
          {step.attempt > 1 && <span className="text-xs text-muted">attempt {step.attempt}</span>}
        </summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div>
            <p className="text-xs text-muted">Input</p>
            <pre className="mt-1 overflow-x-auto rounded bg-background p-2 text-xs">{JSON.stringify(step.input_summary, null, 2)}</pre>
          </div>
          <div>
            <p className="text-xs text-muted">Output</p>
            <pre className="mt-1 overflow-x-auto rounded bg-background p-2 text-xs">{JSON.stringify(step.output_summary, null, 2)}</pre>
          </div>
        </div>
      </details>
      {step.error_message && (
        <p className="mt-1 text-xs text-danger">
          {step.error_category}: {step.error_message}
        </p>
      )}
    </li>
  )
}

function Events() {
  const [params, setParams] = useSearchParams()
  const action = params.get('action') ?? ''
  const { data: events = [], isLoading } = useActivity(action)
  const timezone = useTimezone()
  return (
    <div className="space-y-3">
      <select aria-label="Event type" className={cn(fieldClass, 'mt-0 max-w-xs')} value={action} onChange={(e) => setParams({ tab: 'events', ...(e.target.value && { action: e.target.value }) })}>
        <option value="">All events</option>
        <option value="opportunity.">Opportunities</option>
        <option value="company.">Companies</option>
        <option value="workflow.">Workflows</option>
        <option value="integration.">Connections</option>
        <option value="sheets.">Google Sheets</option>
        <option value="settings.">Settings</option>
      </select>
      {isLoading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
          {events.map((event) => (
            <li key={event.id} className="flex flex-wrap gap-3 px-4 py-2">
              <span className="w-36 shrink-0 text-xs text-muted">{formatDateTime(event.created_at, timezone)}</span>
              <span className="w-48 shrink-0 font-mono text-xs">{event.action}</span>
              <span className="min-w-0 flex-1 text-xs">{String(event.details.summary ?? '')}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
