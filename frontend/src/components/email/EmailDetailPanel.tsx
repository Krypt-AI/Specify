import { ArrowLeft, ExternalLink, Paperclip, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { useTimezone } from '@/api/account'
import { useEmail, useReprocessEmail } from '@/api/emails'
import type { EmailDetail } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { formatBytes, formatDateTime } from '@/lib/utils'

import { ConfidenceMeter, GroupBadge, LabelChip, StatusBadge, SuspiciousBadge } from './badges'
import { ClassificationForm } from './ClassificationForm'
import { DraftReplyButton } from './DraftReplyButton'
import { EmailOpportunity } from './EmailOpportunity'

const SOURCE_LABELS = { ai: 'AI', rule: 'Your rule', user: 'You', fallback: 'Not classified' } as const

export function EmailDetailPanel({ emailId, onClose }: { emailId: string; onClose: () => void }) {
  const { data: email, isLoading, isError } = useEmail(emailId)
  const timezone = useTimezone()

  if (isLoading) return <Card className="text-sm text-muted">Loading email…</Card>
  if (isError || !email) return <Card className="text-sm text-danger">This email could not be loaded.</Card>

  const recipients = email.recipients.map((r) => r.name || r.email).join(', ')

  return (
    <Card className="min-w-0 space-y-5">
      <div className="flex items-start gap-3">
        <button onClick={onClose} className="mt-1 lg:hidden" aria-label="Back to the list">
          <ArrowLeft className="size-5" />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold break-words">{email.subject || '(no subject)'}</h2>
          <p className="mt-1 text-sm break-words">
            {email.sender_name ? `${email.sender_name} <${email.sender_email}>` : email.sender_email}
          </p>
          <p className="text-xs text-muted">
            {formatDateTime(email.received_at, timezone)}
            {recipients && ` · to ${recipients}`}
          </p>
        </div>
        <a
          href={email.gmail_thread_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          Gmail <ExternalLink className="size-3.5" aria-hidden />
        </a>
      </div>

      <ClassificationSummary email={email} />
      <EmailOpportunity email={email} />
      {email.extracted_data.dates && email.extracted_data.dates.length > 0 && (
        <section aria-label="Dates found" className="rounded-md border border-border p-3 text-sm">
          <h3 className="font-medium">Dates found</h3>
          <ul className="mt-1 space-y-1">
            {email.extracted_data.dates.map((found) => (
              <li key={`${found.kind}-${found.text}`} className="flex flex-wrap items-center gap-2">
                <span className="capitalize text-muted">{found.kind}:</span> “{found.text}”
                {found.ambiguous ? (
                  <span className="rounded-full bg-warning/15 px-2 text-xs text-warning">Check this date</span>
                ) : (
                  <span className="text-xs text-muted">
                    {found.date}
                    {found.time && ` ${found.time}`}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      <DraftReplyButton email={email} />

      <section aria-label="Message">
        <div className="max-h-[28rem] overflow-y-auto rounded-md bg-background p-4 text-sm leading-relaxed break-words whitespace-pre-wrap">
          {email.body_text || (
            <span className="text-muted">
              {email.body_purged_at
                ? 'The text of this email was removed from Specify under your retention setting. It is still in Gmail.'
                : 'This email has no text content.'}
            </span>
          )}
        </div>
        {email.body_truncated && (
          <p className="mt-2 text-xs text-muted">Long message shortened. Open it in Gmail to read everything.</p>
        )}
      </section>

      {email.attachments.length > 0 && (
        <section aria-label="Attachments">
          <h3 className="text-sm font-medium">Attachments</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {email.attachments.map((attachment) => (
              <li key={attachment.filename} className="flex items-center gap-2">
                <Paperclip className="size-3.5 text-muted" aria-hidden />
                {attachment.filename}
                <span className="text-xs text-muted">{formatBytes(attachment.size)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted">Specify never downloads or opens attachments.</p>
        </section>
      )}
    </Card>
  )
}

function ClassificationSummary({ email }: { email: EmailDetail }) {
  const [editing, setEditing] = useState(false)
  const reprocess = useReprocessEmail(email.id)
  const needsReview = email.processing_status === 'review_required'
  const busy = email.processing_status === 'pending' || email.processing_status === 'processing'

  return (
    <section aria-label="Classification" className="space-y-3 rounded-md border border-border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={email.processing_status} />
        {email.primary_group && <GroupBadge group={email.primary_group} />}
        {email.secondary_groups.map((group) => (
          <GroupBadge key={group} group={group} secondary />
        ))}
        {email.label && <LabelChip label={email.label} />}
        {!email.label && email.label_suggestion && <LabelChip label={email.label_suggestion} suggested />}
        {email.is_suspicious && <SuspiciousBadge />}
        <span className="ml-auto">
          <ConfidenceMeter value={email.confidence} />
        </span>
      </div>

      {email.classification_explanation && (
        <p className="text-sm">
          {email.classification_source && (
            <span className="font-medium">{SOURCE_LABELS[email.classification_source]}: </span>
          )}
          {email.classification_explanation}
        </p>
      )}
      {email.suspicious_reasons.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-danger">
          {email.suspicious_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {email.processing_error && <p className="text-sm text-danger">{email.processing_error}</p>}

      {needsReview || editing ? (
        <ClassificationForm key={email.id} email={email} onDone={editing ? () => setEditing(false) : undefined} />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setEditing(true)} disabled={busy}>
            Change
          </Button>
          <Button variant="ghost" onClick={() => reprocess.mutate()} disabled={busy || reprocess.isPending}>
            <RefreshCw className="size-4" aria-hidden /> Classify again
          </Button>
        </div>
      )}
    </section>
  )
}
