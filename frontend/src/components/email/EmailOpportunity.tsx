import { Briefcase } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { useCreateOpportunity } from '@/api/recruitment'
import type { EmailDetail } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, fieldClass } from '@/components/ui/field'
import { STATUS_INFO } from '@/lib/recruitment'

/** The opportunity this email belongs to, or a way to create one for a recruitment email. */
export function EmailOpportunity({ email }: { email: EmailDetail }) {
  const [creating, setCreating] = useState(false)
  const opportunity = email.opportunity

  if (opportunity) {
    const status = STATUS_INFO[opportunity.status]
    return (
      <section aria-label="Opportunity" className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3 text-sm">
        <Briefcase className="size-4 text-muted" aria-hidden />
        <Link to={`/opportunities?id=${opportunity.id}`} className="font-medium text-primary hover:underline">
          {opportunity.job_title}
          {opportunity.company_name && ` at ${opportunity.company_name}`}
        </Link>
        <Badge tone={status.tone}>{status.label}</Badge>
      </section>
    )
  }
  if (email.primary_group !== 'recruitment') return null

  return (
    <section aria-label="Opportunity" className="space-y-2 rounded-md border border-border p-3 text-sm">
      {email.recruitment_note && <p className="text-muted">{email.recruitment_note}</p>}
      {creating ? (
        <CreateOpportunityForm email={email} onDone={() => setCreating(false)} />
      ) : (
        <Button variant="outline" onClick={() => setCreating(true)}>
          Create opportunity
        </Button>
      )}
    </section>
  )
}

function CreateOpportunityForm({ email, onDone }: { email: EmailDetail; onDone: () => void }) {
  const create = useCreateOpportunity()
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState(email.extracted_data.organization ?? '')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate(
      { job_title: title.trim(), company_name: company.trim() || undefined, from_email_id: email.id },
      { onSuccess: onDone },
    )
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <Field label="Job title">
        <input className={fieldClass} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
      </Field>
      <Field label="Company">
        <input className={fieldClass} value={company} onChange={(e) => setCompany(e.target.value)} maxLength={200} />
      </Field>
      <p className="text-xs text-muted sm:col-span-2">The sender is saved as the recruiter. Add other details on the Opportunities page.</p>
      <div className="flex items-center gap-3 sm:col-span-2">
        <Button type="submit" disabled={create.isPending}>
          Create
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        {create.isError && <span className="text-danger">{create.error.message}</span>}
      </div>
    </form>
  )
}
