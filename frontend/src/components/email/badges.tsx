import { ShieldAlert, Tag } from 'lucide-react'

import type { LabelRef, MailGroup, ProcessingStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { GROUPS } from '@/lib/groups'

const STATUS: Record<ProcessingStatus, { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' }> = {
  pending: { label: 'Queued', tone: 'neutral' },
  processing: { label: 'Classifying', tone: 'neutral' },
  classified: { label: 'Labeled', tone: 'success' },
  review_required: { label: 'Needs review', tone: 'warning' },
  failed: { label: 'Failed', tone: 'danger' },
}

export function StatusBadge({ status }: { status: ProcessingStatus }) {
  const { label, tone } = STATUS[status]
  return <Badge tone={tone}>{label}</Badge>
}

export function GroupBadge({ group, secondary = false }: { group: MailGroup; secondary?: boolean }) {
  return <Badge tone={secondary ? 'neutral' : 'success'}>{GROUPS[group].label.replace(' Emails', '')}</Badge>
}

export function LabelChip({ label, suggested = false }: { label: Pick<LabelRef, 'name'>; suggested?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs">
      <Tag className="size-3 text-muted" aria-hidden />
      {label.name}
      {suggested && <span className="text-muted">(suggested)</span>}
    </span>
  )
}

export function ConfidenceMeter({ value }: { value: number | null }) {
  if (value === null) return null
  const percent = Math.round(value * 100)
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted" title="Classification confidence">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-border" aria-hidden>
        <span
          className={percent >= 80 ? 'block h-full bg-success' : percent >= 60 ? 'block h-full bg-warning' : 'block h-full bg-danger'}
          style={{ width: `${percent}%` }}
        />
      </span>
      {percent}%
    </span>
  )
}

export function SuspiciousBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-danger/15 px-2 py-0.5 text-xs font-medium text-danger">
      <ShieldAlert className="size-3" aria-hidden />
      Suspicious
    </span>
  )
}
