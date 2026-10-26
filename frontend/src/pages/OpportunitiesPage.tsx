import { Target } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { useOpportunities } from '@/api/recruitment'
import type { OpportunityStatus } from '@/api/types'
import { DuplicatesCard } from '@/components/recruitment/DuplicatesCard'
import { OpportunityList } from '@/components/recruitment/OpportunityList'
import { OpportunityView } from '@/components/recruitment/OpportunityView'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { fieldClass } from '@/components/ui/field'
import { STATUSES, STATUS_INFO } from '@/lib/recruitment'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 25

export function OpportunitiesPage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get('status') as OpportunityStatus | null) ?? undefined
  const q = params.get('q') ?? ''
  const page = Number(params.get('page') ?? 1)
  const selectedId = params.get('id')
  const { data, isLoading } = useOpportunities({ status, q: q || undefined, page })

  const update = (changes: Record<string, string | null>) =>
    setParams((current) => {
      const next = new URLSearchParams(current)
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      if (!('page' in changes) && !('id' in changes)) next.delete('page')
      return next
    })

  const total = data?.total ?? 0

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Opportunities</h1>
        <p className="mt-1 text-sm text-muted">Every job opportunity found in your recruitment email or added by you.</p>
      </div>
      <DuplicatesCard entityType="opportunity" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className={cn('min-w-0 space-y-3', selectedId && 'hidden lg:block')} aria-label="Opportunities">
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              type="search"
              aria-label="Search opportunities"
              placeholder="Search title or company"
              defaultValue={q}
              onKeyDown={(e) => e.key === 'Enter' && update({ q: e.currentTarget.value.trim() || null })}
              onBlur={(e) => e.currentTarget.value.trim() !== q && update({ q: e.currentTarget.value.trim() || null })}
              className={cn(fieldClass, 'mt-0')}
            />
            <select
              aria-label="Status"
              className={cn(fieldClass, 'mt-0')}
              value={status ?? ''}
              onChange={(e) => update({ status: e.target.value || null })}
            >
              <option value="">Any status</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_INFO[s].label}
                </option>
              ))}
            </select>
          </div>
          {isLoading ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : !data || data.items.length === 0 ? (
            <EmptyState
              icon={Target}
              title="No opportunities"
              description={status || q ? 'Try a different filter.' : 'Opportunities appear here once recruitment emails are processed.'}
            />
          ) : (
            <>
              <OpportunityList items={data.items} selectedId={selectedId} onSelect={(id) => update({ id })} />
              <div className="flex items-center justify-between text-sm text-muted">
                <span>{total} total</span>
                <div className="flex gap-1">
                  <Button variant="ghost" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
                    Previous
                  </Button>
                  <Button variant="ghost" disabled={page * PAGE_SIZE >= total} onClick={() => update({ page: String(page + 1) })}>
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}
        </section>
        {selectedId ? (
          <OpportunityView key={selectedId} id={selectedId} mode="manage" onClose={() => update({ id: null })} />
        ) : (
          <div className="hidden items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted lg:flex">
            Select an opportunity to see its details
          </div>
        )}
      </div>
    </div>
  )
}
