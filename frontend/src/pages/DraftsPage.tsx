import { FileText } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { useTimezone } from '@/api/account'
import { useDrafts } from '@/api/drafts'
import { DraftEditor } from '@/components/drafts/DraftEditor'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { fieldClass } from '@/components/ui/field'
import { SCENARIO_LABELS } from '@/lib/drafts'
import { GROUPS } from '@/lib/groups'
import { cn, formatShortDate } from '@/lib/utils'

const STATUS_TONE = { generating: 'neutral', ready: 'success', failed: 'danger', discarded: 'neutral' } as const

export function DraftsPage() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const selectedId = params.get('id')
  const { data: drafts = [], isLoading } = useDrafts(status)
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
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Drafts</h1>
        <p className="mt-1 text-sm text-muted">Replies Specify prepared for you. They wait in Gmail until you send them yourself.</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className={cn('min-w-0 space-y-3', selectedId && 'hidden lg:block')} aria-label="Drafts">
          <select aria-label="Status" className={cn(fieldClass, 'mt-0')} value={status} onChange={(e) => update({ status: e.target.value || null })}>
            <option value="">Active drafts</option>
            <option value="generating">Being written</option>
            <option value="ready">Ready</option>
            <option value="discarded">Discarded</option>
          </select>
          {isLoading ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : drafts.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No drafts"
              description="Drafts appear when you make a decision on an opportunity, or when you choose “Draft a reply” on an email."
            />
          ) : (
            <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
              {drafts.map((draft) => (
                <li key={draft.id}>
                  <button
                    onClick={() => update({ id: draft.id })}
                    className={cn('block w-full px-4 py-3 text-left hover:bg-background', draft.id === selectedId && 'bg-primary/5')}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{draft.subject}</span>
                      <span className="shrink-0 text-xs text-muted">{formatShortDate(draft.updated_at, timezone)}</span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted">
                      To {draft.recipient} · {SCENARIO_LABELS[draft.scenario] ?? draft.scenario}
                      {draft.email.primary_group && ` · ${GROUPS[draft.email.primary_group].label}`}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge tone={STATUS_TONE[draft.status]}>{draft.status === 'generating' ? 'Being written' : draft.status}</Badge>
                      {draft.warnings.length > 0 && <Badge tone="warning">Check before sending</Badge>}
                      {draft.status === 'ready' && !draft.gmail_draft_id && <Badge>Not in Gmail</Badge>}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        {selectedId ? (
          <DraftEditor key={selectedId} id={selectedId} onClose={() => update({ id: null })} />
        ) : (
          <div className="hidden items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted lg:flex">
            Select a draft to review it
          </div>
        )}
      </div>
    </div>
  )
}
