import { ExternalLink, RefreshCw } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { useTimezone } from '@/api/account'
import {
  useCreateSpreadsheet,
  useRemoveSpreadsheet,
  useResolveConflict,
  useSaveSheetsSettings,
  useSelectSpreadsheet,
  useSheetConflicts,
  useSheets,
  useSyncJobs,
  useSyncSheets,
  useRetrySync,
} from '@/api/sheets'
import type { MailGroup, SheetEntity, SheetsSettings, SheetsStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'
import { Toggle } from '@/components/ui/toggle'
import { GROUP_LIST } from '@/lib/groups'
import { cn, formatDateTime } from '@/lib/utils'

import { SaveBar } from './SaveBar'

const ENTITY_LABELS: Record<SheetEntity, string> = {
  companies: 'Companies',
  opportunities: 'Opportunities',
  applications: 'Applications',
  activity: 'Activity Log',
  emails: 'Email Tracker (optional)',
}

export function SheetsSection() {
  const { data: status, isLoading } = useSheets()
  if (isLoading || !status) return <p className="text-sm text-muted">Loading…</p>
  if (!status.connected) {
    return (
      <Card>
        <CardHeader title="Google Sheets" description="Connect Google Sheets on the Accounts tab first." />
      </Card>
    )
  }
  if (!status.spreadsheet || !status.settings) return <ChooseSpreadsheet />
  return (
    <div className="space-y-4">
      <SpreadsheetCard status={status} />
      <Conflicts count={status.open_conflicts} />
      <WorksheetSettings key={status.spreadsheet.id} status={status} settings={status.settings} />
      <SyncHistory />
    </div>
  )
}

function ChooseSpreadsheet() {
  const select = useSelectSpreadsheet()
  const create = useCreateSpreadsheet()
  const [link, setLink] = useState('')
  const [title, setTitle] = useState('Specify Recruitment Tracker')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    select.mutate(link.trim())
  }

  return (
    <Card className="space-y-5">
      <CardHeader
        title="Google Sheets"
        description="Keep companies, opportunities, applications and activity in a spreadsheet. Rows are matched by ID, and columns you add yourself are left alone."
      />
      <div className="space-y-2">
        <h3 className="text-sm font-medium">Create a new spreadsheet</h3>
        <div className="flex flex-wrap gap-2">
          <input className={cn(fieldClass, 'mt-0 max-w-sm')} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Spreadsheet name" />
          <Button onClick={() => create.mutate(title.trim())} disabled={create.isPending || !title.trim()}>
            Create
          </Button>
        </div>
        {create.isError && <p className="text-sm text-danger">{create.error.message}</p>}
      </div>
      <form onSubmit={submit} className="space-y-2">
        <h3 className="text-sm font-medium">Or use an existing spreadsheet</h3>
        <div className="flex flex-wrap gap-2">
          <input
            className={cn(fieldClass, 'mt-0 max-w-lg')}
            value={link}
            onChange={(e) => setLink(e.target.value)}
            placeholder="https://docs.google.com/spreadsheets/d/…"
            aria-label="Spreadsheet link"
            required
          />
          <Button type="submit" variant="outline" disabled={select.isPending}>
            Use this spreadsheet
          </Button>
        </div>
        {select.isError && <p className="text-sm text-danger">{select.error.message}</p>}
      </form>
    </Card>
  )
}

function SpreadsheetCard({ status }: { status: SheetsStatus }) {
  const sync = useSyncSheets()
  const remove = useRemoveSpreadsheet()
  const timezone = useTimezone()
  const job = status.last_job
  const busy = job?.status === 'queued' || job?.status === 'running' || sync.isPending

  return (
    <Card>
      <CardHeader
        title={status.spreadsheet!.title || 'Spreadsheet'}
        description={
          job
            ? `Last sync ${formatDateTime(job.finished_at ?? job.created_at, timezone)}: ${job.status}${job.last_error ? ` (${job.last_error})` : ''}`
            : 'Not synced yet.'
        }
        action={
          <a href={status.spreadsheet!.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-primary">
            Open <ExternalLink className="size-3.5" aria-hidden />
          </a>
        }
      />
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => sync.mutate()} disabled={busy}>
          <RefreshCw className={cn('size-4', busy && 'animate-spin')} aria-hidden /> Sync now
        </Button>
        <Button
          variant="ghost"
          onClick={() => window.confirm('Stop syncing with this spreadsheet? The spreadsheet itself is not changed.') && remove.mutate()}
        >
          Use a different spreadsheet
        </Button>
      </div>
      {sync.isError && <p className="mt-2 text-sm text-danger">{sync.error.message}</p>}
    </Card>
  )
}

function WorksheetSettings({ status, settings: initial }: { status: SheetsStatus; settings: SheetsSettings }) {
  const [settings, setSettings] = useState(initial)
  const save = useSaveSheetsSettings()
  const update = (entity: SheetEntity, changes: Partial<SheetsSettings['worksheets'][SheetEntity]>) =>
    setSettings((current) => ({ ...current, worksheets: { ...current.worksheets, [entity]: { ...current.worksheets[entity], ...changes } } }))
  const toggleGroup = (group: MailGroup) =>
    setSettings((current) => ({
      ...current,
      email_tracker_groups: current.email_tracker_groups.includes(group)
        ? current.email_tracker_groups.filter((g) => g !== group)
        : [...current.email_tracker_groups, group],
    }))

  return (
    <Card className="space-y-5">
      <CardHeader
        title="Worksheets"
        description="Export: Specify fills the worksheet, and edits made in Sheets are shown to you as conflicts instead of being overwritten. Two-way: edits to editable columns are imported."
      />
      <Toggle
        checked={settings.auto_sync}
        onChange={(auto_sync) => setSettings({ ...settings, auto_sync })}
        label="Sync automatically"
        description="Shortly after changes in Specify, and every 15 minutes to pick up edits made in Sheets."
      />
      {(Object.keys(ENTITY_LABELS) as SheetEntity[]).map((entity) => {
        const worksheet = settings.worksheets[entity]
        return (
          <details key={entity} className="rounded-md border border-border p-3" open={entity === 'opportunities'}>
            <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium">
              {ENTITY_LABELS[entity]}
              {!worksheet.enabled && <Badge>Off</Badge>}
              {worksheet.enabled && worksheet.direction === 'two_way' && <Badge tone="success">Two-way</Badge>}
            </summary>
            <div className="mt-3 space-y-3">
              <Toggle checked={worksheet.enabled} onChange={(enabled) => update(entity, { enabled })} label="Sync this worksheet" />
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Worksheet name">
                  <input className={fieldClass} value={worksheet.title} onChange={(e) => update(entity, { title: e.target.value })} maxLength={100} />
                </Field>
                {status.two_way_capable[entity] && (
                  <>
                    <Field label="Direction">
                      <select
                        className={fieldClass}
                        value={worksheet.direction}
                        onChange={(e) => update(entity, { direction: e.target.value as 'export' | 'two_way' })}
                      >
                        <option value="export">Export from Specify</option>
                        <option value="two_way">Two-way</option>
                      </select>
                    </Field>
                    <Field label="When both sides changed">
                      <select
                        className={fieldClass}
                        value={worksheet.source_of_truth}
                        disabled={worksheet.direction !== 'two_way'}
                        onChange={(e) => update(entity, { source_of_truth: e.target.value as 'database' | 'sheets' })}
                      >
                        <option value="database">Ask me (Specify is the source)</option>
                        <option value="sheets">Sheets wins</option>
                      </select>
                    </Field>
                  </>
                )}
              </div>
              {entity === 'emails' && (
                <fieldset>
                  <legend className="text-sm font-medium">Folders to track</legend>
                  <div className="mt-1 flex flex-wrap gap-3">
                    {GROUP_LIST.map((group) => (
                      <label key={group.key} className="flex items-center gap-1.5 text-sm">
                        <input
                          type="checkbox"
                          className="accent-primary"
                          checked={settings.email_tracker_groups.includes(group.key)}
                          onChange={() => toggleGroup(group.key)}
                        />
                        {group.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="py-1 font-normal">Field</th>
                    <th className="py-1 font-normal">Column header in your sheet</th>
                  </tr>
                </thead>
                <tbody>
                  {status.fields[entity].map((field, index) => (
                    <tr key={field.key}>
                      <td className="py-1 pr-3">
                        {field.header}
                        {index === 0 && <span className="text-xs text-muted"> (required)</span>}
                        {field.importable && worksheet.direction === 'two_way' && <span className="text-xs text-success"> · editable</span>}
                      </td>
                      <td className="py-1">
                        <input
                          className={cn(fieldClass, 'mt-0')}
                          value={worksheet.columns[field.key] ?? ''}
                          placeholder="Not synced"
                          aria-label={`Column for ${field.header}`}
                          onChange={(e) => update(entity, { columns: { ...worksheet.columns, [field.key]: e.target.value } })}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )
      })}
      <SaveBar mutation={save} onSave={() => save.mutate(settings)} />
    </Card>
  )
}

function Conflicts({ count }: { count: number }) {
  const { data: conflicts = [] } = useSheetConflicts(count > 0)
  const resolve = useResolveConflict()
  if (count === 0) return null

  return (
    <Card className="border-warning/50">
      <CardHeader title="Changes to review" description="These cells changed in Sheets. Specify won't overwrite them until you choose." />
      <ul className="divide-y divide-border">
        {conflicts.map((conflict) => (
          <li key={conflict.id} className="space-y-2 py-3 text-sm">
            <p>
              <span className="font-medium">{ENTITY_LABELS[conflict.entity]}</span> · {conflict.field_label} · row {conflict.record_id.slice(0, 8)}
            </p>
            <p className="text-muted">{conflict.reason}</p>
            {conflict.field === '__row__' ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => resolve.mutate({ id: conflict.id, resolution: 'restore' })}>
                  Restore the row
                </Button>
                <Button variant="ghost" onClick={() => resolve.mutate({ id: conflict.id, resolution: 'stop_syncing' })}>
                  Stop syncing this record
                </Button>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => resolve.mutate({ id: conflict.id, resolution: 'keep_specify' })}>
                  Keep Specify’s value: {conflict.specify_value || '(empty)'}
                </Button>
                <Button variant="outline" onClick={() => resolve.mutate({ id: conflict.id, resolution: 'keep_sheet' })}>
                  Keep the sheet’s value: {conflict.sheet_value || '(empty)'}
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {resolve.isError && <p className="text-sm text-danger">{resolve.error.message}</p>}
    </Card>
  )
}

function SyncHistory() {
  const { data: jobs = [] } = useSyncJobs(true)
  const retry = useRetrySync()
  const timezone = useTimezone()
  if (jobs.length === 0) return null

  return (
    <Card>
      <CardHeader title="Sync history" />
      <ul className="divide-y divide-border text-sm">
        {jobs.map((job) => {
          const totals = Object.values(job.summary).reduce(
            (sum, s) => ({ created: sum.created + s.created, updated: sum.updated + s.updated, imported: sum.imported + s.imported, conflicts: sum.conflicts + s.conflicts }),
            { created: 0, updated: 0, imported: 0, conflicts: 0 },
          )
          return (
            <li key={job.id} className="flex flex-wrap items-center gap-3 py-2">
              <span className="w-40 text-muted">{formatDateTime(job.created_at, timezone)}</span>
              <Badge tone={job.status === 'succeeded' ? 'success' : job.status === 'failed' ? 'danger' : 'neutral'}>{job.status}</Badge>
              <span className="text-xs text-muted">{job.trigger}</span>
              <span className="min-w-0 flex-1 text-xs">
                {job.status === 'failed'
                  ? job.last_error
                  : `${totals.created} added · ${totals.updated} updated · ${totals.imported} imported · ${totals.conflicts} to review`}
              </span>
              {job.status === 'failed' && (
                <Button variant="outline" onClick={() => retry.mutate(job.id)} disabled={retry.isPending}>
                  Retry
                </Button>
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
