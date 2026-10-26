import { ListChecks } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { useOpportunities } from '@/api/recruitment'
import { OpportunityList } from '@/components/recruitment/OpportunityList'
import { OpportunityView } from '@/components/recruitment/OpportunityView'
import { EmptyState } from '@/components/ui/empty-state'
import { cn } from '@/lib/utils'

/** New opportunities, plus deferred ones whose revisit date has come, waiting for your decision. */
export function DecisionQueuePage() {
  const [params, setParams] = useSearchParams()
  const { data, isLoading } = useOpportunities({ queue: true })
  const items = data?.items ?? []
  const selectedId = params.get('id') ?? items[0]?.id ?? null

  const select = (id: string | null) => setParams(id ? { id } : {})
  const next = () => select(items.find((item) => item.id !== selectedId)?.id ?? null)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Decision Queue</h1>
        <p className="mt-1 text-sm text-muted">Recruitment opportunities waiting for your decision. Suggestions are advice only.</p>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : items.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="Nothing to decide"
          description="New opportunities from recruitment emails appear here. Opportunities you save for later return when their revisit date comes."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <section className={cn('min-w-0', params.get('id') && 'hidden lg:block')} aria-label="Opportunities to decide">
            <OpportunityList items={items} selectedId={selectedId} onSelect={select} />
          </section>
          {selectedId && (
            <OpportunityView key={selectedId} id={selectedId} mode="decide" onClose={() => select(null)} onDecided={next} />
          )}
        </div>
      )}
    </div>
  )
}
