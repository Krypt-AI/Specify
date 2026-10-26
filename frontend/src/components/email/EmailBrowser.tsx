import { ChevronLeft, ChevronRight, Inbox, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useIntegrations } from '@/api/account'
import { useEmails } from '@/api/emails'
import { useLabels } from '@/api/labels'
import type { EmailFilters, MailGroup, ProcessingStatus } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { fieldClass } from '@/components/ui/field'
import { cn } from '@/lib/utils'

import { EmailDetailPanel } from './EmailDetailPanel'
import { EmailList } from './EmailList'

const PAGE_SIZE = 25
const STATUS_OPTIONS: { value: ProcessingStatus | ''; label: string }[] = [
  { value: '', label: 'Any status' },
  { value: 'review_required', label: 'Needs review' },
  { value: 'classified', label: 'Labeled' },
  { value: 'pending', label: 'Queued' },
  { value: 'failed', label: 'Failed' },
]

/** Filterable email list with a detail panel. Filters live in the URL so views can be linked. */
export function EmailBrowser({ folder }: { folder?: MailGroup }) {
  const [params, setParams] = useSearchParams()
  const filters: EmailFilters = {
    folder,
    q: params.get('q') ?? undefined,
    status: (params.get('status') as ProcessingStatus | null) ?? undefined,
    label_id: params.get('label') ?? undefined,
    unread: params.get('unread') === 'true' || undefined,
    page: Number(params.get('page') ?? 1),
    page_size: PAGE_SIZE,
  }
  const selectedId = params.get('email')
  const { data, isLoading, isError } = useEmails(filters)
  const { data: labels = [] } = useLabels()

  const updateParams = (changes: Record<string, string | null>) =>
    setParams((current) => {
      const next = new URLSearchParams(current)
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      if (!('page' in changes) && !('email' in changes)) next.delete('page')
      return next
    })

  const page = filters.page ?? 1
  const total = data?.total ?? 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <section className={cn('min-w-0 space-y-3', selectedId && 'hidden lg:block')} aria-label="Emails">
        <div className="grid gap-2 sm:grid-cols-2">
          <SearchField query={filters.q ?? ''} onSearch={(q) => updateParams({ q: q || null })} />
          <select
            aria-label="Status"
            className={cn(fieldClass, 'mt-0')}
            value={filters.status ?? ''}
            onChange={(e) => updateParams({ status: e.target.value || null })}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Label"
            className={cn(fieldClass, 'mt-0')}
            value={filters.label_id ?? ''}
            onChange={(e) => updateParams({ label: e.target.value || null })}
          >
            <option value="">Any label</option>
            {labels
              .filter((label) => !label.system_key)
              .map((label) => (
                <option key={label.id} value={label.id}>
                  {label.name}
                </option>
              ))}
          </select>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={filters.unread ?? false}
              onChange={(e) => updateParams({ unread: e.target.checked ? 'true' : null })}
              className="accent-primary"
            />
            Unread only
          </label>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted">Loading emails…</p>
        ) : isError ? (
          <p className="text-sm text-danger">Emails could not be loaded.</p>
        ) : data && data.items.length > 0 ? (
          <>
            <EmailList emails={data.items} selectedId={selectedId} onSelect={(id) => updateParams({ email: id })} />
            <div className="flex items-center justify-between text-sm text-muted">
              <span>
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  className="px-2"
                  disabled={page <= 1}
                  onClick={() => updateParams({ page: String(page - 1) })}
                  aria-label="Previous page"
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  className="px-2"
                  disabled={page >= lastPage}
                  onClick={() => updateParams({ page: String(page + 1) })}
                  aria-label="Next page"
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </>
        ) : (
          <NoEmails filtered={Boolean(filters.q || filters.status || filters.label_id || filters.unread)} />
        )}
      </section>

      {selectedId ? (
        <EmailDetailPanel emailId={selectedId} onClose={() => updateParams({ email: null })} />
      ) : (
        <div className="hidden items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted lg:flex">
          Select an email to see its details
        </div>
      )}
    </div>
  )
}

/** Debounced search input that also follows the URL when the query changes elsewhere. */
function SearchField({ query, onSearch }: { query: string; onSearch: (query: string) => void }) {
  const [search, setSearch] = useState(query)
  const [syncedQuery, setSyncedQuery] = useState(query)
  if (query !== syncedQuery) {
    setSyncedQuery(query)
    if (query !== search.trim()) setSearch(query)
  }

  useEffect(() => {
    if (search.trim() === query) return
    const timer = setTimeout(() => onSearch(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search, query, onSearch])

  return (
    <label className="relative sm:col-span-2">
      <span className="sr-only">Search emails</span>
      <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search sender, subject or text"
        className={cn(fieldClass, 'mt-0 pl-9')}
      />
    </label>
  )
}

function NoEmails({ filtered }: { filtered: boolean }) {
  const { data: integrations = [] } = useIntegrations()
  const gmailConnected = integrations.find((i) => i.provider === 'gmail')?.connected
  if (filtered) {
    return <EmptyState icon={Search} title="No matching emails" description="Try a different search or filter." />
  }
  return (
    <EmptyState
      icon={Inbox}
      title="No emails here yet"
      description={
        gmailConnected
          ? 'New emails appear here after they are synchronized and classified.'
          : 'Connect Gmail so Specify can start organizing your email.'
      }
      action={
        !gmailConnected && (
          <Link to="/settings" className="text-sm font-medium text-primary hover:underline">
            Connect Gmail
          </Link>
        )
      }
    />
  )
}
