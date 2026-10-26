import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { useRequestReply } from '@/api/drafts'
import type { EmailDetail } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field, fieldClass } from '@/components/ui/field'
import { SCENARIO_LABELS } from '@/lib/drafts'
import { cn } from '@/lib/utils'

const DEFAULT_SCENARIO = { university: 'university_reply', certifications: 'certification_reply' } as const

/** Ask for a reply draft to any email; the draft opens on the Drafts page while it is written. */
export function DraftReplyButton({ email }: { email: EmailDetail }) {
  const [open, setOpen] = useState(false)
  const request = useRequestReply(email.id)
  const navigate = useNavigate()
  const [scenario, setScenario] = useState<string>(
    DEFAULT_SCENARIO[email.primary_group as keyof typeof DEFAULT_SCENARIO] ?? 'general_reply',
  )
  const [instructions, setInstructions] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    request.mutate({ scenario, instructions }, { onSuccess: (draft) => draft && navigate(`/drafts?id=${draft.id}`) })
  }

  if (!open) {
    return (
      <Button variant="outline" onClick={() => setOpen(true)}>
        Draft a reply
      </Button>
    )
  }
  return (
    <form onSubmit={submit} className="space-y-3 rounded-md border border-border p-3">
      <Field label="Kind of reply">
        <select className={fieldClass} value={scenario} onChange={(e) => setScenario(e.target.value)}>
          {Object.entries(SCENARIO_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="What should it say? (optional)">
        <textarea
          className={cn(fieldClass, 'h-20 py-2')}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="Ask whether the deadline can move to Friday."
          maxLength={1000}
        />
      </Field>
      <div className="flex gap-2">
        <Button type="submit" disabled={request.isPending}>
          Write draft
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {request.isError && <p className="text-sm text-danger">{request.error.message}</p>}
    </form>
  )
}
