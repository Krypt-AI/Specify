import { useDuplicates, useResolveDuplicate } from '@/api/recruitment'
import type { DuplicateCandidate } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'

/** Possible duplicates for the user to confirm. Nothing is merged without a click. */
export function DuplicatesCard({ entityType }: { entityType: DuplicateCandidate['entity_type'] }) {
  const { data = [] } = useDuplicates()
  const resolve = useResolveDuplicate()
  const pending = data.filter((d) => d.entity_type === entityType)
  if (pending.length === 0) return null

  return (
    <Card className="border-warning/50">
      <CardHeader
        title={`Possible duplicate ${entityType === 'company' ? 'companies' : 'opportunities'}`}
        description="Merging moves everything onto the existing record. Keep them separate when they are different."
      />
      <ul className="divide-y divide-border">
        {pending.map((candidate) => (
          <li key={candidate.id} className="flex flex-wrap items-center gap-3 py-3">
            <div className="min-w-0 flex-1 text-sm">
              <p>
                <span className="font-medium">{candidate.record_name}</span> may be the same as{' '}
                <span className="font-medium">{candidate.candidate_name}</span>
              </p>
              <p className="text-xs text-muted">{candidate.reason}</p>
            </div>
            <Button
              variant="outline"
              disabled={resolve.isPending}
              onClick={() =>
                window.confirm(`Merge "${candidate.record_name}" into "${candidate.candidate_name}"?`) &&
                resolve.mutate({ id: candidate.id, action: 'merge' })
              }
            >
              Merge
            </Button>
            <Button variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: candidate.id, action: 'dismiss' })}>
              Keep separate
            </Button>
          </li>
        ))}
      </ul>
      {resolve.isError && <p className="text-sm text-danger">{resolve.error.message}</p>}
    </Card>
  )
}
