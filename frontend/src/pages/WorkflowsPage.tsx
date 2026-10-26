import { Workflow as WorkflowIcon } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useCurrentUser } from '@/api/account'
import { useCreateWorkflow, useDeleteWorkflow, useSetWorkflowEnabled, useWorkflowTemplates, useWorkflows } from '@/api/workflows'
import type { Workflow } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Field, fieldClass } from '@/components/ui/field'
import { Toggle } from '@/components/ui/toggle'
import { RUN_STATUS } from '@/lib/workflows'
import { formatShortDate } from '@/lib/utils'

export function WorkflowsPage() {
  const { data: workflows = [], isLoading } = useWorkflows()
  const { data: user } = useCurrentUser()
  const paused = user?.preferences.automation.paused

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Workflows</h1>
        <p className="mt-1 text-sm text-muted">The steps Specify takes for every new email. Edit them visually, test them, and see every run.</p>
      </div>
      {paused && (
        <p className="rounded-md bg-warning/10 px-4 py-3 text-sm">
          Automation is paused. No workflow starts or continues until you resume it in{' '}
          <Link to="/settings?tab=automation" className="font-medium text-primary hover:underline">
            Settings → Automation
          </Link>
          .
        </p>
      )}
      <NewWorkflow />
      {isLoading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : workflows.length === 0 ? (
        <EmptyState icon={WorkflowIcon} title="No workflows" description="Create one from a template above." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {workflows.map((workflow) => (
            <WorkflowCard key={workflow.id} workflow={workflow} />
          ))}
        </div>
      )}
    </div>
  )
}

function WorkflowCard({ workflow }: { workflow: Workflow }) {
  const setEnabled = useSetWorkflowEnabled(workflow.id)
  const remove = useDeleteWorkflow()
  const last = workflow.last_run
  return (
    <Card className="space-y-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <Link to={`/workflows/${workflow.id}`} className="font-semibold text-primary hover:underline">
            {workflow.name}
          </Link>
          <p className="text-sm text-muted">{workflow.description}</p>
        </div>
        {workflow.is_default && <Badge>Default</Badge>}
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-muted">
        <span>{workflow.trigger_type === 'scheduled_trigger' ? 'On a schedule' : 'For every new email'}</span>
        {workflow.waiting_runs > 0 && <Badge tone="warning">{workflow.waiting_runs} waiting</Badge>}
        {workflow.failed_runs > 0 && <Badge tone="danger">{workflow.failed_runs} failed</Badge>}
        {last && (
          <span>
            Last run {formatShortDate(last.created_at)}: {RUN_STATUS[last.status].label.toLowerCase()}
          </span>
        )}
      </div>
      {workflow.problems.length > 0 && <p className="text-sm text-danger">Needs fixing before it can run ({workflow.problems.length} problems).</p>}
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-36">
          <Toggle
            checked={workflow.enabled}
            onChange={(enabled) => setEnabled.mutate(enabled)}
            label={workflow.enabled ? 'Enabled' : 'Disabled'}
            disabled={setEnabled.isPending}
          />
        </div>
        <Link to={`/workflows/${workflow.id}`} className="text-sm font-medium text-primary hover:underline">
          Open builder
        </Link>
        {!workflow.is_default && (
          <Button variant="ghost" onClick={() => window.confirm(`Delete “${workflow.name}”?`) && remove.mutate(workflow.id)}>
            Delete
          </Button>
        )}
      </div>
      {setEnabled.isError && <p className="text-sm text-danger">{setEnabled.error.message}</p>}
    </Card>
  )
}

function NewWorkflow() {
  const { data: templates = [] } = useWorkflowTemplates()
  const create = useCreateWorkflow()
  const navigate = useNavigate()
  const [template, setTemplate] = useState('')
  const [name, setName] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate(
      { name: name.trim() || templates.find((t) => t.key === template)?.name || 'New workflow', template: template || undefined },
      { onSuccess: (workflow) => navigate(`/workflows/${workflow.id}`) },
    )
  }

  return (
    <Card>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Field label="Start from">
          <select className={fieldClass} value={template} onChange={(e) => setTemplate(e.target.value)}>
            <option value="">An empty workflow</option>
            {templates.map((t) => (
              <option key={t.key} value={t.key}>
                {t.name}
                {t.built_in ? '' : ' (your template)'}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Name">
          <input className={fieldClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </Field>
        <Button type="submit" disabled={create.isPending}>
          New workflow
        </Button>
      </form>
      <p className="mt-2 text-xs text-muted">New workflows start switched off. Test them, then enable them.</p>
    </Card>
  )
}
