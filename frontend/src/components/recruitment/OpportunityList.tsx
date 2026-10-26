import { useTimezone } from '@/api/account'
import type { OpportunitySummary } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { formatSalary, STATUS_INFO } from '@/lib/recruitment'
import { cn, formatShortDate } from '@/lib/utils'

export function OpportunityList({
  items,
  selectedId,
  onSelect,
}: {
  items: OpportunitySummary[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const timezone = useTimezone()
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
      {items.map((item) => {
        const status = STATUS_INFO[item.status]
        const salary = formatSalary(item)
        return (
          <li key={item.id}>
            <button
              onClick={() => onSelect(item.id)}
              aria-current={item.id === selectedId}
              className={cn('block w-full px-4 py-3 text-left transition hover:bg-background', item.id === selectedId && 'bg-primary/5')}
            >
              <div className="flex items-baseline gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.job_title}</span>
                <time className="shrink-0 text-xs text-muted" dateTime={item.date_received}>
                  {formatShortDate(item.date_received, timezone)}
                </time>
              </div>
              <p className="mt-0.5 truncate text-sm text-muted">
                {[item.company?.name, item.location, item.work_arrangement].filter(Boolean).join(' · ') || 'Company unknown'}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <Badge tone={status.tone}>{status.label}</Badge>
                {item.priority === 'high' && <Badge tone="danger">High priority</Badge>}
                {salary && <span className="text-xs text-muted">{salary}</span>}
              </div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
