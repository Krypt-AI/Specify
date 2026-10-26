import { Trash2 } from 'lucide-react'

import type { ConfigFieldSpec, NodeTypeSpec } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field, fieldClass } from '@/components/ui/field'
import { TagInput } from '@/components/ui/tag-input'
import { Toggle } from '@/components/ui/toggle'
import { cn } from '@/lib/utils'

/** Settings form for one step, generated from the step type's field list. */
export function NodeInspector({
  nodeId,
  spec,
  config,
  problems,
  onChange,
  onDelete,
}: {
  nodeId: string
  spec: NodeTypeSpec
  config: Record<string, unknown>
  problems: string[]
  onChange: (config: Record<string, unknown>) => void
  onDelete: () => void
}) {
  const set = (key: string, value: unknown) => onChange({ ...config, [key]: value })

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs text-muted">{spec.category}</p>
        <h3 className="font-semibold">{spec.label}</h3>
        <p className="mt-1 text-sm text-muted">{spec.description}</p>
        <p className="mt-1 font-mono text-xs text-muted">id: {nodeId}</p>
      </div>
      {problems.map((problem) => (
        <p key={problem} className="text-sm text-danger">
          {problem}
        </p>
      ))}
      {spec.fields.length === 0 && <p className="text-sm text-muted">This step has no settings.</p>}
      {spec.fields.map((field) => (
        <FieldEditor key={field.key} field={field} value={config[field.key] ?? field.default} onChange={(value) => set(field.key, value)} />
      ))}
      {spec.retryable && <p className="text-xs text-muted">Temporary failures are retried automatically; the wait doubles each time.</p>}
      {!spec.trigger && (
        <Button variant="danger" onClick={onDelete}>
          <Trash2 className="size-4" aria-hidden /> Remove step
        </Button>
      )}
    </div>
  )
}

function FieldEditor({ field, value, onChange }: { field: ConfigFieldSpec; value: unknown; onChange: (value: unknown) => void }) {
  if (field.kind === 'boolean') {
    return <Toggle checked={Boolean(value)} onChange={onChange} label={field.label} description={field.help} />
  }
  if (field.kind === 'tags') {
    return <TagInput label={field.label} values={(value as string[]) ?? []} onChange={onChange} />
  }
  return (
    <Field label={field.label} hint={field.help}>
      {field.kind === 'select' ? (
        <select className={fieldClass} value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
      ) : field.kind === 'number' ? (
        <input
          type="number"
          className={fieldClass}
          value={Number(value)}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      ) : field.kind === 'textarea' ? (
        <textarea className={cn(fieldClass, 'h-20 py-2')} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input className={fieldClass} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
      )}
    </Field>
  )
}
