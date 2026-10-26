import { BarChart3 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { useAnalytics } from '@/api/reminders'
import { BarList, type BarDatum } from '@/components/charts/BarList'
import { ChartTooltip } from '@/components/charts/ChartTooltip'
import { Card, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { fieldClass } from '@/components/ui/field'
import { GROUP_LIST } from '@/lib/groups'
import { DECISION_LABELS, STATUS_INFO } from '@/lib/recruitment'
import { cn } from '@/lib/utils'

const RANGES = [30, 90, 180, 365]
const SERIES = [
  { key: 'recruitment_emails', name: 'Recruitment emails', color: 'var(--chart-1)' },
  { key: 'opportunities_created', name: 'Opportunities created', color: 'var(--chart-2)' },
  { key: 'decisions', name: 'Decisions', color: 'var(--chart-3)' },
] as const

export function AnalyticsPage() {
  const [days, setDays] = useState(90)
  const { data, isLoading } = useAnalytics(days)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Analytics</h1>
          <p className="mt-1 text-sm text-muted">Calculated from your own emails, records and workflows.</p>
        </div>
        <select aria-label="Time range" className={cn(fieldClass, 'mt-0 w-auto')} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {RANGES.map((range) => (
            <option key={range} value={range}>
              Last {range} days
            </option>
          ))}
        </select>
      </div>
      {isLoading || !data ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <AnalyticsBody data={data} />
      )}
    </div>
  )
}

function AnalyticsBody({ data }: { data: NonNullable<ReturnType<typeof useAnalytics>['data']> }) {
  const emailBars: BarDatum[] = GROUP_LIST.map((g) => ({ label: g.label, value: data.emails_by_group[g.key] ?? 0 }))
  const statusBars = sortedBars(data.opportunities_by_status, (key) => STATUS_INFO[key as keyof typeof STATUS_INFO]?.label ?? key)
  const decisionBars = sortedBars(data.decisions_by_outcome, (key) => DECISION_LABELS[key as keyof typeof DECISION_LABELS] ?? key)
  const runs = data.workflow_runs
  const finished = (runs.completed ?? 0) + (runs.failed ?? 0)
  const successRate = finished ? Math.round(((runs.completed ?? 0) / finished) * 100) : null
  const nothing = emailBars.every((b) => b.value === 0) && statusBars.length === 0 && finished === 0

  if (nothing) {
    return <EmptyState icon={BarChart3} title="No data in this period" description="Charts fill in as Specify processes your email." />
  }

  return (
    <div className="space-y-4">
      <section aria-label="Follow-ups and workflows" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Follow-ups completed" value={data.follow_ups.completed} />
        <Stat label="Follow-ups open" value={data.follow_ups.open} />
        <Stat label="Follow-ups overdue" value={data.follow_ups.overdue} tone={data.follow_ups.overdue ? 'danger' : undefined} />
        <Card className="p-4">
          <p className="text-xs text-muted">Workflow success</p>
          <p className="mt-1 text-xl font-semibold">{successRate === null ? '–' : `${successRate}%`}</p>
          {successRate !== null && (
            <>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border" role="meter" aria-valuenow={successRate} aria-valuemin={0} aria-valuemax={100} aria-label="Workflow success rate">
                <div className="h-full rounded-full" style={{ width: `${successRate}%`, background: 'var(--chart-sequential)' }} />
              </div>
              <p className="mt-1 text-xs text-muted">
                {runs.completed ?? 0} completed · {runs.failed ?? 0} failed
              </p>
            </>
          )}
        </Card>
      </section>

      <ChartCard title="Recruitment activity by week" table={<ActivityTable data={data} />}>
        <div className="h-64" role="img" aria-label="Weekly recruitment emails, opportunities created and decisions">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.activity_by_week} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
              <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
              <XAxis dataKey="week_start" tickFormatter={shortDate} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={{ stroke: 'var(--chart-grid)' }} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTooltip />} labelFormatter={(value) => `Week of ${shortDate(String(value))}`} cursor={{ stroke: 'var(--chart-axis)', strokeDasharray: '3 3' }} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              {SERIES.map((series) => (
                <Line
                  key={series.key}
                  type="monotone"
                  dataKey={series.key}
                  name={series.name}
                  stroke={series.color}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--color-surface)' }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Emails by folder" table={<Table rows={emailBars} />}>
          <BarList data={emailBars} valueLabel="Emails" />
        </ChartCard>
        <ChartCard title="Opportunities by status" table={<Table rows={statusBars} />}>
          {statusBars.length ? <BarList data={statusBars} valueLabel="Opportunities" /> : <p className="text-sm text-muted">No opportunities yet.</p>}
        </ChartCard>
        <ChartCard title="Decisions by outcome" table={<Table rows={decisionBars} />}>
          {decisionBars.length ? <BarList data={decisionBars} valueLabel="Decisions" /> : <p className="text-sm text-muted">No decisions in this period.</p>}
        </ChartCard>
      </div>
    </div>
  )
}

function sortedBars(counts: Record<string, number>, label: (key: string) => string): BarDatum[] {
  return Object.entries(counts)
    .filter(([, value]) => value > 0)
    .map(([key, value]) => ({ label: label(key), value }))
    .sort((a, b) => b.value - a.value)
}

function shortDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'danger' }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={cn('mt-1 text-xl font-semibold', tone === 'danger' && 'text-danger')}>{value}</p>
    </Card>
  )
}

/** Every chart has a table view: identity never relies on color alone. */
function ChartCard({ title, table, children }: { title: string; table: ReactNode; children: ReactNode }) {
  const [asTable, setAsTable] = useState(false)
  return (
    <Card>
      <CardHeader
        title={title}
        action={
          <button className="text-xs text-primary hover:underline" onClick={() => setAsTable(!asTable)}>
            {asTable ? 'Show chart' : 'Show table'}
          </button>
        }
      />
      {asTable ? table : children}
    </Card>
  )
}

function Table({ rows }: { rows: BarDatum[] }) {
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((row) => (
          <tr key={row.label} className="border-b border-border last:border-0">
            <td className="py-1.5">{row.label}</td>
            <td className="py-1.5 text-right tabular-nums">{row.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ActivityTable({ data }: { data: NonNullable<ReturnType<typeof useAnalytics>['data']> }) {
  return (
    <div className="max-h-64 overflow-y-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="py-1 font-normal">Week of</th>
            {SERIES.map((s) => (
              <th key={s.key} className="py-1 text-right font-normal">
                {s.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.activity_by_week.map((week) => (
            <tr key={week.week_start} className="border-b border-border last:border-0">
              <td className="py-1.5">{shortDate(week.week_start)}</td>
              {SERIES.map((s) => (
                <td key={s.key} className="py-1.5 text-right tabular-nums">
                  {week[s.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
