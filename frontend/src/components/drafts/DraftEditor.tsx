import { AlertTriangle, ArrowLeft, ExternalLink, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { useCurrentUser, useTimezone } from '@/api/account'
import { useDiscardDraft, useDraft, useRegenerateDraft, useSaveDraftToGmail, useUpdateDraft } from '@/api/drafts'
import type { Draft } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'
import { gmailDraftUrl, SCENARIO_LABELS, TONE_OPTIONS } from '@/lib/drafts'
import { cn, formatDateTime } from '@/lib/utils'

export function DraftEditor({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: draft, isLoading } = useDraft(id)
  if (isLoading || !draft) return <Card className="text-sm text-muted">Loading draft…</Card>
  return <DraftForm key={`${draft.id}-${draft.status}-${draft.updated_at}`} draft={draft} onClose={onClose} />
}

function DraftForm({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const { data: account } = useCurrentUser()
  const timezone = useTimezone()
  const update = useUpdateDraft(draft.id)
  const regenerate = useRegenerateDraft(draft.id)
  const saveToGmail = useSaveDraftToGmail(draft.id)
  const discard = useDiscardDraft(draft.id)
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const [tone, setTone] = useState(draft.tone)
  const [instructions, setInstructions] = useState(draft.instructions)
  const writing = draft.status === 'generating' || regenerate.isPending
  const changed = subject !== draft.subject || body !== draft.body

  return (
    <Card className="min-w-0 space-y-4">
      <div className="flex items-start gap-3">
        <button onClick={onClose} className="mt-1 lg:hidden" aria-label="Back to the list">
          <ArrowLeft className="size-5" />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">{SCENARIO_LABELS[draft.scenario] ?? draft.scenario}</h2>
          <p className="text-sm text-muted">
            To {draft.recipient} · reply to “{draft.email.subject}”
          </p>
        </div>
        {draft.gmail_message_id && account && draft.status === 'ready' && (
          <a
            href={gmailDraftUrl(account.email, draft.gmail_message_id)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            Open in Gmail <ExternalLink className="size-3.5" aria-hidden />
          </a>
        )}
      </div>

      <p className="rounded-md bg-background px-3 py-2 text-xs text-muted">
        Specify never sends email. Review the draft, then send it yourself from Gmail.
      </p>

      {writing ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <RefreshCw className="size-4 animate-spin" aria-hidden /> Writing the draft…
        </p>
      ) : (
        <>
          {draft.error && <p className="rounded-md bg-warning/10 px-3 py-2 text-sm">{draft.error}</p>}
          {draft.warnings.length > 0 && (
            <ul className="space-y-1">
              {draft.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-sm text-warning">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {warning}
                </li>
              ))}
            </ul>
          )}
          <Field label="Subject">
            <input className={fieldClass} value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={500} />
          </Field>
          <Field label="Message">
            <textarea
              className={cn(fieldClass, 'h-72 py-2 leading-relaxed')}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => update.mutate({ subject, body })} disabled={!changed || update.isPending}>
              Save changes
            </Button>
            {!draft.gmail_draft_id && (
              <Button variant="outline" onClick={() => saveToGmail.mutate()} disabled={saveToGmail.isPending}>
                Save to Gmail
              </Button>
            )}
            <Button
              variant="danger"
              onClick={() => window.confirm('Discard this draft? It is also removed from Gmail.') && discard.mutate(undefined, { onSuccess: onClose })}
            >
              Discard
            </Button>
            <span className="text-xs text-muted">
              {draft.generated_by === 'ai' ? 'Written by AI' : 'Written from your template'}
              {draft.edited_by_user && ' · edited by you'}
              {draft.gmail_synced_at && ` · saved in Gmail ${formatDateTime(draft.gmail_synced_at, timezone)}`}
            </span>
          </div>
          {(update.isError || saveToGmail.isError) && (
            <p className="text-sm text-danger">{(update.error ?? saveToGmail.error)?.message}</p>
          )}
          <details className="rounded-md border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">Write it again</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="Tone">
                <input className={fieldClass} list="tone-options" value={tone} onChange={(e) => setTone(e.target.value)} maxLength={40} />
                <datalist id="tone-options">
                  {TONE_OPTIONS.map((option) => (
                    <option key={option} value={option} />
                  ))}
                </datalist>
              </Field>
              <Field label="Guidance (optional)" className="sm:col-span-2">
                <textarea
                  className={cn(fieldClass, 'h-20 py-2')}
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  placeholder="Mention I'm available from next Monday."
                  maxLength={1000}
                />
              </Field>
              <div className="sm:col-span-2">
                <Button variant="outline" onClick={() => regenerate.mutate({ tone, instructions })}>
                  <RefreshCw className="size-4" aria-hidden /> Write again
                </Button>
                <span className="ml-2 text-xs text-muted">Replaces the current text, including your edits.</span>
              </div>
            </div>
          </details>
        </>
      )}
      {draft.status === 'failed' && <Badge tone="danger">Failed</Badge>}
    </Card>
  )
}
