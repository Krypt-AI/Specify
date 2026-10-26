import { useState, type FormEvent } from 'react'

import { useUpdateOpportunity } from '@/api/recruitment'
import type { OpportunityDetail, OpportunityFields, Priority, WorkArrangement } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field, fieldClass } from '@/components/ui/field'
import { cn } from '@/lib/utils'

const text = (value: string) => value.trim() || null
const number = (value: string) => (value.trim() === '' ? null : Number(value))

/** Edit the opportunity's details. Values you enter here are stored as given. */
export function OpportunityEditForm({ opportunity, onDone }: { opportunity: OpportunityDetail; onDone: () => void }) {
  const update = useUpdateOpportunity(opportunity.id)
  const [form, setForm] = useState({
    job_title: opportunity.job_title,
    job_reference: opportunity.job_reference ?? '',
    employment_type: opportunity.employment_type ?? '',
    work_arrangement: opportunity.work_arrangement ?? '',
    location: opportunity.location ?? '',
    salary_min: opportunity.salary_min?.toString() ?? '',
    salary_max: opportunity.salary_max?.toString() ?? '',
    salary_currency: opportunity.salary_currency ?? '',
    salary_period: opportunity.salary_period ?? '',
    application_deadline: opportunity.application_deadline ?? '',
    priority: opportunity.priority,
    job_description: opportunity.job_description,
    notes: opportunity.notes,
  })
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const changes: OpportunityFields = {
      job_title: form.job_title.trim(),
      job_reference: text(form.job_reference),
      employment_type: text(form.employment_type),
      work_arrangement: (form.work_arrangement || null) as WorkArrangement | null,
      location: text(form.location),
      salary_min: number(form.salary_min),
      salary_max: number(form.salary_max),
      salary_currency: text(form.salary_currency.toUpperCase()),
      salary_period: form.salary_period || null,
      application_deadline: form.application_deadline || null,
      priority: form.priority as Priority,
      job_description: form.job_description,
      notes: form.notes,
    }
    update.mutate(changes, { onSuccess: onDone })
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <Field label="Job title" className="sm:col-span-2">
        <input className={fieldClass} value={form.job_title} onChange={set('job_title')} maxLength={200} required />
      </Field>
      <Field label="Reference">
        <input className={fieldClass} value={form.job_reference} onChange={set('job_reference')} maxLength={100} />
      </Field>
      <Field label="Employment type">
        <input className={fieldClass} value={form.employment_type} onChange={set('employment_type')} placeholder="Full-time" maxLength={40} />
      </Field>
      <Field label="Work arrangement">
        <select className={fieldClass} value={form.work_arrangement} onChange={set('work_arrangement')}>
          <option value="">Not stated</option>
          <option value="remote">Remote</option>
          <option value="hybrid">Hybrid</option>
          <option value="onsite">On-site</option>
        </select>
      </Field>
      <Field label="Location">
        <input className={fieldClass} value={form.location} onChange={set('location')} maxLength={200} />
      </Field>
      <Field label="Salary from">
        <input type="number" min={0} className={fieldClass} value={form.salary_min} onChange={set('salary_min')} />
      </Field>
      <Field label="Salary to">
        <input type="number" min={0} className={fieldClass} value={form.salary_max} onChange={set('salary_max')} />
      </Field>
      <Field label="Currency" hint="Three letters, such as MYR or USD.">
        <input className={fieldClass} value={form.salary_currency} onChange={set('salary_currency')} maxLength={3} pattern="[A-Za-z]{3}" />
      </Field>
      <Field label="Per">
        <select className={fieldClass} value={form.salary_period} onChange={set('salary_period')}>
          <option value="">Not stated</option>
          {['year', 'month', 'week', 'day', 'hour'].map((period) => (
            <option key={period} value={period}>
              {period}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Application deadline">
        <input type="date" className={fieldClass} value={form.application_deadline} onChange={set('application_deadline')} />
      </Field>
      <Field label="Priority">
        <select className={fieldClass} value={form.priority} onChange={set('priority')}>
          <option value="low">Low</option>
          <option value="normal">Normal</option>
          <option value="high">High</option>
        </select>
      </Field>
      <Field label="Job description" className="sm:col-span-2">
        <textarea className={cn(fieldClass, 'h-28 py-2')} value={form.job_description} onChange={set('job_description')} maxLength={4000} />
      </Field>
      <Field label="Notes" className="sm:col-span-2">
        <textarea className={cn(fieldClass, 'h-20 py-2')} value={form.notes} onChange={set('notes')} />
      </Field>
      <div className="flex items-center gap-3 sm:col-span-2">
        <Button type="submit" disabled={update.isPending}>
          Save details
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        {update.isError && <span className="text-sm text-danger">{update.error.message}</span>}
      </div>
    </form>
  )
}
