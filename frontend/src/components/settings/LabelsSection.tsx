import { Check, Pencil, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { useCreateLabel, useLabels, useUpdateLabel } from '@/api/labels'
import type { Label } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { fieldClass } from '@/components/ui/field'
import { Toggle } from '@/components/ui/toggle'
import { cn } from '@/lib/utils'

const ORIGIN = { ai: 'AI', user: 'You', system: 'Status' } as const

export function LabelsSection() {
  const { data: labels = [], isLoading } = useLabels()
  const create = useCreateLabel()
  const [name, setName] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate({ name: name.trim() }, { onSuccess: () => setName('') })
  }

  return (
    <Card>
      <CardHeader
        title="Labels"
        description="Labels appear in Gmail under Specify/. Disabling a label stops new emails from getting it; emails that already have it keep it."
      />
      <form onSubmit={submit} className="mb-4 flex flex-wrap gap-2">
        <input
          className={cn(fieldClass, 'mt-0 max-w-xs')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New label name"
          minLength={2}
          maxLength={60}
          aria-label="New label name"
          required
        />
        <Button type="submit" variant="outline" disabled={create.isPending}>
          Add label
        </Button>
        {create.isError && <span className="self-center text-sm text-danger">{create.error.message}</span>}
      </form>
      {isLoading ? (
        <p className="text-sm text-muted">Loading labels…</p>
      ) : labels.length === 0 ? (
        <p className="text-sm text-muted">No labels yet. They are created as Specify classifies your emails.</p>
      ) : (
        <ul className="divide-y divide-border">
          {labels.map((label) => (
            <LabelRow key={label.id} label={label} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function LabelRow({ label }: { label: Label }) {
  const update = useUpdateLabel()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(label.name)

  const save = () => update.mutate({ id: label.id, name: name.trim() }, { onSuccess: () => setEditing(false) })

  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        {editing ? (
          <div className="flex items-center gap-1">
            <input
              className={cn(fieldClass, 'mt-0 max-w-xs')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-label="Label name"
              autoFocus
            />
            <Button variant="ghost" className="px-2" onClick={save} aria-label="Save name" disabled={update.isPending}>
              <Check className="size-4" />
            </Button>
            <Button variant="ghost" className="px-2" onClick={() => setEditing(false)} aria-label="Cancel">
              <X className="size-4" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className={cn('truncate text-sm font-medium', !label.enabled && 'text-muted line-through')}>
              {label.name}
            </span>
            <Button variant="ghost" className="h-7 px-1.5" onClick={() => setEditing(true)} aria-label={`Rename ${label.name}`}>
              <Pencil className="size-3.5" />
            </Button>
          </div>
        )}
        {label.description && <p className="mt-0.5 text-xs text-muted">{label.description}</p>}
        {update.isError && <p className="mt-1 text-xs text-danger">{update.error.message}</p>}
      </div>
      <Badge>{ORIGIN[label.created_by]}</Badge>
      <span className="w-20 text-right text-xs text-muted">{label.email_count} emails</span>
      {!label.system_key && (
        <div className="w-28">
          <Toggle
            checked={label.enabled}
            onChange={(enabled) => update.mutate({ id: label.id, enabled })}
            label={label.enabled ? 'Enabled' : 'Disabled'}
          />
        </div>
      )}
    </li>
  )
}
