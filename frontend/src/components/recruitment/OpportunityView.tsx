import { AlertTriangle, ArrowLeft, ExternalLink, Lightbulb } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { useTimezone } from '@/api/account'
import { useOpportunity, useUpdateOpportunity } from '@/api/recruitment'
import type { OpportunityDetail, OpportunityStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { fieldClass } from '@/components/ui/field'
import { DECISION_LABELS, formatSalary, MISSING_LABELS, STATUSES, STATUS_INFO } from '@/lib/recruitment'
import { cn, formatDateTime, formatShortDate } from '@/lib/utils'

import { DecisionForm } from './DecisionForm'
import { OpportunityEditForm } from './OpportunityEditForm'

/**
 * One opportunity. "decide" shows the decision panel for the queue; "manage" adds status and
 * detail editing for the Opportunities page.
 */
export function OpportunityView({
  id,
  mode,
  onClose,
  onDecided,
}: {
  id: string
  mode: 'decide' | 'manage'
  onClose: () => void
  onDecided?: () => void
}) {
  const { data: opportunity, isLoading, isError } = useOpportunity(id)
  const [editing, setEditing] = useState(false)

  if (isLoading) return <Card className="text-sm text-muted">Loading opportunity…</Card>
  if (isError || !opportunity) return <Card className="text-sm text-danger">This opportunity could not be loaded.</Card>

  const status = STATUS_INFO[opportunity.status]

  return (
    <Card className="min-w-0 space-y-5">
      <div className="flex items-start gap-3">
        <button onClick={onClose} className="mt-1 lg:hidden" aria-label="Back to the list">
          <ArrowLeft className="size-5" />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold break-words">{opportunity.job_title}</h2>
          <p className="text-sm text-muted">{opportunity.company?.name ?? 'Company unknown'}</p>
        </div>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>

      {opportunity.duplicates.length > 0 && (
        <p className="rounded-md bg-warning/10 px-3 py-2 text-sm">
          This may duplicate another opportunity. Review it on the Opportunities page.
        </p>
      )}

      <Advice opportunity={opportunity} />
      <Facts opportunity={opportunity} />

      {mode === 'manage' && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <StatusSelect opportunity={opportunity} />
            {!editing && (
              <Button variant="outline" onClick={() => setEditing(true)}>
                Edit details
              </Button>
            )}
          </div>
          {editing && <OpportunityEditForm opportunity={opportunity} onDone={() => setEditing(false)} />}
        </section>
      )}

      {(mode === 'decide' || !editing) && (
        <section className="rounded-md border border-border p-4">
          <DecisionForm key={opportunity.id} opportunity={opportunity} onDecided={onDecided} />
        </section>
      )}

      <Conversation opportunity={opportunity} />
      <History opportunity={opportunity} />
    </Card>
  )
}

function Advice({ opportunity }: { opportunity: OpportunityDetail }) {
  return (
    <section className="space-y-2">
      {opportunity.advice && (
        <div className="flex gap-2 rounded-md bg-primary/5 p-3 text-sm">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <p>
            <span className="font-medium">
              Suggestion ({opportunity.advice.source === 'ai' ? 'AI' : 'rules'}): {DECISION_LABELS[opportunity.advice.decision]}.
            </span>{' '}
            {opportunity.advice.explanation} <span className="text-muted">The decision is yours.</span>
          </p>
        </div>
      )}
      {opportunity.missing_information.length > 0 && (
        <p className="text-sm">
          <span className="font-medium">Missing: </span>
          {opportunity.missing_information.map((key) => MISSING_LABELS[key]).join(', ')}
        </p>
      )}
      {opportunity.preference_flags.map((flag) => (
        <p key={flag} className="flex items-start gap-2 text-sm text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {flag}
        </p>
      ))}
    </section>
  )
}

function Facts({ opportunity }: { opportunity: OpportunityDetail }) {
  const timezone = useTimezone()
  const deadline = opportunity.application_deadline
    ? new Date(`${opportunity.application_deadline}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' })
    : opportunity.deadline_text
  const facts: [string, ReactNode][] = [
    ['Company', opportunity.company?.name],
    ['Recruiter', opportunity.recruiter && `${opportunity.recruiter.name || opportunity.recruiter.email} (${opportunity.recruiter.email})`],
    ['Salary', formatSalary(opportunity)],
    ['Work arrangement', opportunity.work_arrangement],
    ['Location', opportunity.location],
    ['Employment type', opportunity.employment_type],
    ['Deadline', deadline],
    ['Reference', opportunity.job_reference],
    ['Received', formatDateTime(opportunity.date_received, timezone)],
    ['Revisit on', opportunity.next_follow_up_at && formatDateTime(opportunity.next_follow_up_at, timezone)],
  ]
  return (
    <section className="space-y-3">
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {facts
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className="break-words">{value}</dd>
            </div>
          ))}
      </dl>
      {opportunity.job_description && (
        <p className="rounded-md bg-background p-3 text-sm leading-relaxed whitespace-pre-wrap">{opportunity.job_description}</p>
      )}
      {opportunity.benefits.length > 0 && <p className="text-sm">Benefits: {opportunity.benefits.join(', ')}</p>}
      {opportunity.notes && <p className="text-sm text-muted">Notes: {opportunity.notes}</p>}
    </section>
  )
}

function StatusSelect({ opportunity }: { opportunity: OpportunityDetail }) {
  const update = useUpdateOpportunity(opportunity.id)
  return (
    <label className="flex items-center gap-2 text-sm">
      Status
      <select
        className={cn(fieldClass, 'mt-0 w-auto')}
        value={opportunity.status}
        disabled={update.isPending}
        onChange={(e) => update.mutate({ status: e.target.value as OpportunityStatus })}
      >
        {STATUSES.map((status) => (
          <option key={status} value={status}>
            {STATUS_INFO[status].label}
          </option>
        ))}
      </select>
      {update.isError && <span className="text-danger">{update.error.message}</span>}
    </label>
  )
}

function Conversation({ opportunity }: { opportunity: OpportunityDetail }) {
  const timezone = useTimezone()
  if (opportunity.emails.length === 0) return null
  return (
    <section aria-label="Related emails">
      <h3 className="text-sm font-medium">Emails</h3>
      <ul className="mt-2 space-y-2">
        {opportunity.emails.map((email) => (
          <li key={email.id} className="rounded-md border border-border p-3 text-sm">
            <div className="flex items-baseline gap-2">
              <span className="min-w-0 flex-1 truncate font-medium">{email.subject || '(no subject)'}</span>
              <span className="shrink-0 text-xs text-muted">{formatShortDate(email.received_at, timezone)}</span>
              <a href={email.gmail_thread_url} target="_blank" rel="noreferrer" className="shrink-0 text-primary" aria-label="Open in Gmail">
                <ExternalLink className="size-3.5" />
              </a>
            </div>
            <p className="text-xs text-muted">{email.sender_name || email.sender_email}</p>
            <p className="mt-1 line-clamp-2 text-xs">{email.snippet}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function History({ opportunity }: { opportunity: OpportunityDetail }) {
  const timezone = useTimezone()
  if (opportunity.decisions.length === 0) return null
  return (
    <section aria-label="Decision history">
      <h3 className="text-sm font-medium">Your decisions</h3>
      <ul className="mt-2 space-y-1 text-sm">
        {opportunity.decisions.map((entry) => (
          <li key={entry.id}>
            <span className="text-muted">{formatShortDate(entry.created_at, timezone)}:</span>{' '}
            {entry.custom_decision ?? DECISION_LABELS[entry.decision]}
            {entry.notes && <span className="text-muted"> ({entry.notes})</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}
