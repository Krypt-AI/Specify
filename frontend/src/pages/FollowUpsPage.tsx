import { Bell } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { useTimezone } from '@/api/account'
import { useCreateFollowUp, useFollowUpAction, useFollowUps } from '@/api/reminders'
import type { FollowUp } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Field, fieldClass } from '@/components/ui/field'
import { cn, formatDateTime } from '@/lib/utils'

const KIND_LABELS: Record<string, string> = {
  recruiter: 'Recruiter follow-up',
  decision: 'Decision',
  deadline: 'Deadline',
  payment: 'Payment',
  exam: 'Exam',
  interview: 'Interview',
  renewal: 'Renewal',
  reply: 'Reply needed',
  follow_up: 'Reminder',
}

const SNOOZE = [
  { label: 'Tomorrow', days: 1 },
  { label: '3 days', days: 3 },
  { label: 'Next week', days: 7 },
]

export function FollowUpsPage() {
  const [status, setStatus] = useState<'open' | 'done'>('open')
  const { data: tasks = [], isLoading } = useFollowUps(status)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Follow-ups</h1>
        <p className="mt-1 text-sm text-muted">
          Reminders from your decisions, from dates in your email, and ones you add yourself. Specify never creates calendar events.
        </p>
      </div>
      <NewFollowUp />
      <nav className="flex gap-1 border-b border-border">
        {(['open', 'done'] as const).map((value) => (
          <button
            key={value}
            onClick={() => setStatus(value)}
            className={cn('-mb-px border-b-2 px-3 py-2 text-sm', status === value ? 'border-primary font-medium text-primary' : 'border-transparent text-muted')}
          >
            {value === 'open' ? 'To do' : 'Done'}
          </button>
        ))}
      </nav>
      {isLoading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : tasks.length === 0 ? (
        <EmptyState icon={Bell} title={status === 'open' ? 'Nothing to follow up' : 'Nothing completed yet'} description="Reminders appear here as they are created." />
      ) : (
        <ul className="space-y-2">
          {tasks.map((task) => (
            <FollowUpRow key={task.id} task={task} />
          ))}
        </ul>
      )}
    </div>
  )
}

function FollowUpRow({ task }: { task: FollowUp }) {
  const action = useFollowUpAction()
  const timezone = useTimezone()
  const snooze = (days: number) => action.mutate({ id: task.id, action: 'snooze', until: new Date(Date.now() + days * 86_400_000).toISOString() })

  return (
    <li>
      <Card className={cn('flex flex-wrap items-start gap-3 p-4', task.overdue && 'border-danger/50')}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{task.title}</span>
            <Badge>{KIND_LABELS[task.kind] ?? task.kind}</Badge>
            {task.overdue && <Badge tone="danger">Overdue</Badge>}
            {task.snoozed_until && task.status === 'open' && !task.overdue && <Badge>Snoozed</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted">
            {task.status === 'done' ? `Done ${formatDateTime(task.completed_at, timezone)}` : `Due ${formatDateTime(task.due_at, timezone)}`}
            {task.context && (
              <>
                {' · '}
                {task.opportunity_id ? (
                  <Link to={`/opportunities?id=${task.opportunity_id}`} className="text-primary hover:underline">
                    {task.context}
                  </Link>
                ) : (
                  <Link to={`/inbox?email=${task.email_message_id}`} className="text-primary hover:underline">
                    {task.context}
                  </Link>
                )}
              </>
            )}
          </p>
          {task.notes && <p className="mt-1 text-sm">{task.notes}</p>}
        </div>
        {task.status === 'open' ? (
          <div className="flex flex-wrap items-center gap-1">
            <Button onClick={() => action.mutate({ id: task.id, action: 'complete' })}>Done</Button>
            <select
              aria-label="Snooze"
              className={cn(fieldClass, 'mt-0 w-auto')}
              value=""
              onChange={(e) => e.target.value && snooze(Number(e.target.value))}
            >
              <option value="">Snooze…</option>
              {SNOOZE.map((option) => (
                <option key={option.days} value={option.days}>
                  {option.label}
                </option>
              ))}
            </select>
            <Button variant="ghost" onClick={() => action.mutate({ id: task.id, action: 'cancel' })}>
              Remove
            </Button>
          </div>
        ) : (
          <Button variant="ghost" onClick={() => action.mutate({ id: task.id, action: 'reopen' })}>
            Reopen
          </Button>
        )}
      </Card>
    </li>
  )
}

function NewFollowUp() {
  const create = useCreateFollowUp()
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate({ title: title.trim(), due_at: new Date(due).toISOString() }, { onSuccess: () => setTitle('') })
  }

  return (
    <Card>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_14rem_auto] sm:items-end">
        <Field label="New reminder">
          <input className={fieldClass} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required placeholder="Call the recruiter back" />
        </Field>
        <Field label="When">
          <input type="datetime-local" className={fieldClass} value={due} onChange={(e) => setDue(e.target.value)} required />
        </Field>
        <Button type="submit" disabled={create.isPending}>
          Add
        </Button>
      </form>
      {create.isError && <p className="mt-2 text-sm text-danger">{create.error.message}</p>}
    </Card>
  )
}
