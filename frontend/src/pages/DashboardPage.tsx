import { BarChart3 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { useIntegrations, useTimezone } from '@/api/account'
import { useEmailStats } from '@/api/emails'
import { useOpportunityStats } from '@/api/recruitment'
import { useDashboardSummary } from '@/api/reminders'
import type { User } from '@/api/types'
import { SyncControl } from '@/components/SyncControl'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { GROUP_LIST } from '@/lib/groups'
import { cn, formatDateTime } from '@/lib/utils'

export function DashboardPage({ user }: { user: User }) {
  const { data: stats, isLoading } = useEmailStats()
  const { data: integrations = [] } = useIntegrations()
  const { data: recruitment } = useOpportunityStats()
  const { data: summary } = useDashboardSummary()
  const timezone = useTimezone()
  const gmail = integrations.find((i) => i.provider === 'gmail')
  const sheets = integrations.find((i) => i.provider === 'sheets')

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Welcome{user.name ? `, ${user.name}` : ''}</h1>
          <p className="mt-1 text-sm text-muted">Your email processing overview.</p>
        </div>
        <SyncControl />
      </div>

      {isLoading ? (
        <p className="text-sm text-muted">Loading metrics…</p>
      ) : !stats || stats.total === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No email processed yet"
          description="Metrics appear here once Specify synchronizes and classifies your Gmail. Every number comes from your real data."
          action={
            !gmail?.connected && (
              <Link to="/settings" className="text-sm font-medium text-primary hover:underline">
                Connect Gmail in Settings
              </Link>
            )
          }
        />
      ) : (
        <>
          <section aria-label="Email metrics" className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="Emails processed" value={stats.total} />
            <Metric label="Needs review" value={stats.needs_review} to="/inbox?status=review_required" highlight={stats.needs_review > 0} />
            <Metric label="Unread" value={stats.unread} to="/inbox?unread=true" />
            <Metric label="Queued" value={stats.pending} />
            {GROUP_LIST.map((group) => (
              <Metric key={group.key} label={group.label} value={stats.by_group[group.key]} to={group.path} />
            ))}
            <Metric label="Suspicious" value={stats.suspicious} highlight={stats.suspicious > 0} tone="danger" />
            <Metric label="Failed" value={stats.failed} to="/inbox?status=failed" highlight={stats.failed > 0} tone="danger" />
          </section>
          {recruitment && (
            <section aria-label="Recruitment metrics" className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Metric label="Pending decisions" value={recruitment.decision_queue} to="/decisions" highlight={recruitment.decision_queue > 0} />
              <Metric label="Active opportunities" value={recruitment.active} to="/opportunities" />
              <Metric label="Interviews scheduled" value={recruitment.interviews_scheduled} to="/opportunities?status=interview_scheduled" />
              <Metric label="Offers received" value={recruitment.offers_received} to="/opportunities?status=offer_received" />
            </section>
          )}
          {summary && (
            <section aria-label="Work to do" className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Metric label="Drafts awaiting review" value={summary.drafts_ready} to="/drafts" />
              <Metric label="Follow-ups due" value={summary.follow_ups_due} to="/follow-ups" highlight={summary.follow_ups_overdue > 0} tone="danger" />
              <Metric label="Workflows waiting" value={summary.workflows_waiting} to="/activity?status=waiting" />
              <Metric label="Failed workflow runs" value={summary.workflows_failed} to="/activity?status=failed" highlight={summary.workflows_failed > 0} tone="danger" />
            </section>
          )}
          <section aria-label="Synchronization" className="grid gap-3 sm:grid-cols-2">
            <Metric label="Last Gmail sync" value={formatDateTime(stats.last_gmail_sync_at, timezone)} />
            <Metric
              label="Last Sheets sync"
              value={sheets?.connected ? formatDateTime(sheets.last_sync_at, timezone) : 'Not connected'}
            />
          </section>
        </>
      )}
    </div>
  )
}

function Metric({
  label,
  value,
  to,
  highlight = false,
  tone = 'warning',
}: {
  label: string
  value: ReactNode
  to?: string
  highlight?: boolean
  tone?: 'warning' | 'danger'
}) {
  const content = (
    <Card className={cn('h-full p-4', to && 'transition hover:border-primary/50')}>
      <p className="text-xs text-muted">{label}</p>
      <p className={cn('mt-1 text-xl font-semibold', highlight && (tone === 'danger' ? 'text-danger' : 'text-warning'))}>
        {value}
      </p>
    </Card>
  )
  return to ? <Link to={to}>{content}</Link> : content
}
