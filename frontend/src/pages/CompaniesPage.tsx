import { ArrowLeft, Building2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useTimezone } from '@/api/account'
import { useCompanies, useCompany, useUpdateCompany } from '@/api/recruitment'
import type { CompanyDetail, CompanyType } from '@/api/types'
import { DuplicatesCard } from '@/components/recruitment/DuplicatesCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Field, fieldClass } from '@/components/ui/field'
import { STATUS_INFO } from '@/lib/recruitment'
import { cn, formatShortDate } from '@/lib/utils'

const TYPE_LABELS: Record<CompanyType, string> = { employer: 'Employer', agency: 'Recruitment agency', unknown: 'Unknown' }

export function CompaniesPage() {
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const { data, isLoading } = useCompanies(query)
  const timezone = useTimezone()
  const selectedId = params.get('id')
  const companies = data?.items ?? []

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Companies</h1>
        <p className="mt-1 text-sm text-muted">Employers and recruitment agencies from your recruitment email.</p>
      </div>
      <DuplicatesCard entityType="company" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className={cn('min-w-0 space-y-3', selectedId && 'hidden lg:block')} aria-label="Companies">
          <input
            type="search"
            aria-label="Search companies"
            placeholder="Search companies"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className={cn(fieldClass, 'mt-0')}
          />
          {isLoading ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : companies.length === 0 ? (
            <EmptyState icon={Building2} title="No companies yet" description="Companies are added as recruitment emails are processed." />
          ) : (
            <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
              {companies.map((company) => (
                <li key={company.id}>
                  <button
                    onClick={() => setParams({ id: company.id })}
                    className={cn('block w-full px-4 py-3 text-left hover:bg-background', company.id === selectedId && 'bg-primary/5')}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{company.name}</span>
                      {company.last_contact_at && (
                        <span className="text-xs text-muted">{formatShortDate(company.last_contact_at, timezone)}</span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-muted">
                      {TYPE_LABELS[company.company_type]} · {company.opportunity_count} opportunities · {company.contact_count} contacts
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        {selectedId ? (
          <CompanyPanel key={selectedId} id={selectedId} onClose={() => setParams({})} />
        ) : (
          <div className="hidden items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted lg:flex">
            Select a company to see its details
          </div>
        )}
      </div>
    </div>
  )
}

function CompanyPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: company, isLoading } = useCompany(id)
  if (isLoading || !company) return <Card className="text-sm text-muted">Loading company…</Card>

  return (
    <Card className="min-w-0 space-y-5">
      <div className="flex items-start gap-3">
        <button onClick={onClose} className="mt-1 lg:hidden" aria-label="Back to the list">
          <ArrowLeft className="size-5" />
        </button>
        <h2 className="min-w-0 flex-1 text-lg font-semibold break-words">{company.name}</h2>
        <Badge>{TYPE_LABELS[company.company_type]}</Badge>
      </div>
      <CompanyForm company={company} />
      <section>
        <h3 className="text-sm font-medium">Contacts</h3>
        {company.contacts.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No contacts yet.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {company.contacts.map((contact) => (
              <li key={contact.id}>
                <span className="font-medium">{contact.name || contact.email}</span>
                {contact.role && <span className="text-muted"> · {contact.role}</span>}
                <span className="text-muted"> · {contact.email}</span>
                {contact.phone && <span className="text-muted"> · {contact.phone}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3 className="text-sm font-medium">Opportunities</h3>
        {company.opportunities.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No opportunities yet.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {company.opportunities.map((opportunity) => (
              <li key={opportunity.id} className="flex items-center gap-2">
                <Link to={`/opportunities?id=${opportunity.id}`} className="text-primary hover:underline">
                  {opportunity.job_title}
                </Link>
                <Badge tone={STATUS_INFO[opportunity.status].tone}>{STATUS_INFO[opportunity.status].label}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Card>
  )
}

function CompanyForm({ company }: { company: CompanyDetail }) {
  const update = useUpdateCompany(company.id)
  const [form, setForm] = useState({
    name: company.name,
    company_type: company.company_type,
    website: company.website ?? '',
    industry: company.industry ?? '',
    country: company.country ?? '',
    location: company.location ?? '',
    notes: company.notes,
  })
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const blankToNull = (value: string) => value.trim() || null
    update.mutate({
      name: form.name.trim(),
      company_type: form.company_type,
      website: blankToNull(form.website),
      industry: blankToNull(form.industry),
      country: blankToNull(form.country),
      location: blankToNull(form.location),
      notes: form.notes,
    })
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <Field label="Name">
        <input className={fieldClass} value={form.name} onChange={set('name')} maxLength={200} required />
      </Field>
      <Field label="Type">
        <select className={fieldClass} value={form.company_type} onChange={set('company_type')}>
          {Object.entries(TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Website">
        <input className={fieldClass} value={form.website} onChange={set('website')} maxLength={500} />
      </Field>
      <Field label="Industry">
        <input className={fieldClass} value={form.industry} onChange={set('industry')} maxLength={120} />
      </Field>
      <Field label="Country">
        <input className={fieldClass} value={form.country} onChange={set('country')} maxLength={80} />
      </Field>
      <Field label="Location">
        <input className={fieldClass} value={form.location} onChange={set('location')} maxLength={200} />
      </Field>
      <Field label="Notes" className="sm:col-span-2">
        <textarea className={cn(fieldClass, 'h-20 py-2')} value={form.notes} onChange={set('notes')} />
      </Field>
      <div className="flex items-center gap-3 sm:col-span-2">
        <Button type="submit" disabled={update.isPending}>
          Save
        </Button>
        {update.isSuccess && <span className="text-sm text-success">Saved</span>}
        {update.isError && <span className="text-sm text-danger">{update.error.message}</span>}
      </div>
      {company.domain && <p className="text-xs text-muted sm:col-span-2">Email domain: {company.domain}</p>}
    </form>
  )
}
