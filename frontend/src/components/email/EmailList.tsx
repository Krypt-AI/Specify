import { useTimezone } from '@/api/account'
import type { EmailSummary } from '@/api/types'
import { STATUS_INFO } from '@/lib/recruitment'
import { cn, formatShortDate } from '@/lib/utils'

import { LabelChip, StatusBadge, SuspiciousBadge } from './badges'

export function EmailList({
  emails,
  selectedId,
  onSelect,
}: {
  emails: EmailSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const timezone = useTimezone()

  return (
    <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
      {emails.map((email) => (
        <li key={email.id}>
          <button
            onClick={() => onSelect(email.id)}
            aria-current={email.id === selectedId}
            className={cn(
              'block w-full px-4 py-3 text-left transition hover:bg-background',
              email.id === selectedId && 'bg-primary/5',
            )}
          >
            <div className="flex items-baseline gap-2">
              {email.is_unread && <span className="size-2 shrink-0 rounded-full bg-primary" aria-label="Unread" />}
              <span className={cn('min-w-0 flex-1 truncate text-sm', email.is_unread && 'font-semibold')}>
                {email.sender_name || email.sender_email}
              </span>
              <time className="shrink-0 text-xs text-muted" dateTime={email.received_at}>
                {formatShortDate(email.received_at, timezone)}
              </time>
            </div>
            <p className={cn('mt-0.5 truncate text-sm', email.is_unread && 'font-medium')}>
              {email.subject || '(no subject)'}
            </p>
            {email.opportunity ? (
              <p className="mt-0.5 truncate text-xs text-primary">
                {email.opportunity.job_title}
                {email.opportunity.company_name && ` · ${email.opportunity.company_name}`} · {STATUS_INFO[email.opportunity.status].label}
              </p>
            ) : (
              <p className="mt-0.5 line-clamp-1 text-xs text-muted">{email.snippet}</p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {email.processing_status !== 'classified' && <StatusBadge status={email.processing_status} />}
              {email.label && <LabelChip label={email.label} />}
              {email.is_suspicious && <SuspiciousBadge />}
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}
