import { useState, type FormEvent } from 'react'

import { useRecordDecision } from '@/api/recruitment'
import type { DecisionName, OpportunityDetail } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field, fieldClass } from '@/components/ui/field'
import { DECISIONS } from '@/lib/recruitment'
import { cn } from '@/lib/utils'

/** The user's decision. The AI's advice preselects nothing: the choice is always the user's. */
export function DecisionForm({ opportunity, onDecided }: { opportunity: OpportunityDetail; onDecided?: () => void }) {
  const record = useRecordDecision(opportunity.id)
  const [decision, setDecision] = useState<DecisionName | null>(null)
  const [custom, setCustom] = useState('')
  const [notes, setNotes] = useState('')
  const latestEmail = opportunity.emails.at(-1)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!decision) return
    record.mutate(
      {
        decision,
        notes,
        ...(decision === 'custom' && { custom_decision: custom }),
        ...(latestEmail && { email_id: latestEmail.id }),
      },
      {
        onSuccess: (result) => {
          if (!result) return // the user cancelled the confirmation
          setDecision(null)
          setNotes('')
          onDecided?.()
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <fieldset>
        <legend className="text-sm font-medium">Your decision</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {DECISIONS.map((option) => (
            <label
              key={option.value}
              className={cn(
                'flex cursor-pointer gap-2 rounded-md border p-3 text-sm transition',
                decision === option.value ? 'border-primary bg-primary/5' : 'border-border hover:bg-background',
              )}
            >
              <input
                type="radio"
                name="decision"
                value={option.value}
                checked={decision === option.value}
                onChange={() => setDecision(option.value)}
                className="mt-0.5 accent-primary"
              />
              <span>
                <span className="block font-medium">
                  {option.label}
                  {opportunity.advice?.decision === option.value && (
                    <span className="ml-1.5 text-xs font-normal text-primary">suggested</span>
                  )}
                </span>
                <span className="block text-xs text-muted">{option.description}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      {decision === 'custom' && (
        <Field label="Describe your decision">
          <input className={fieldClass} value={custom} onChange={(e) => setCustom(e.target.value)} maxLength={200} required />
        </Field>
      )}
      <Field label="Notes (optional)">
        <textarea
          className={cn(fieldClass, 'h-20 py-2')}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={2000}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!decision || record.isPending}>
          Save decision
        </Button>
        <span className="text-xs text-muted">If your decision needs a reply, a draft is saved in Gmail for you to review. Nothing is sent.</span>
      </div>
      {record.isError && <p className="text-sm text-danger">{record.error.message}</p>}
    </form>
  )
}
