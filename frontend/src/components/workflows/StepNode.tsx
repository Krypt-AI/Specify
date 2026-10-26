import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'

import type { NodeTypeSpec } from '@/api/types'
import { HANDLE_LABELS, outputsOf } from '@/lib/workflows'
import { cn } from '@/lib/utils'

export type StepData = { spec: NodeTypeSpec; config: Record<string, unknown>; problem: boolean }
export type StepNodeType = Node<StepData, 'step'>

function summary(spec: NodeTypeSpec, config: Record<string, unknown>) {
  if (spec.key === 'conditional_branch') return `${config.field} ${String(config.operator).replace('_', ' ')} ${config.value ?? ''}`
  if (spec.key === 'notification' || spec.key === 'reminder') return String(config.title ?? '')
  if (spec.key === 'delay') return `${config.minutes} minutes`
  if (spec.key === 'scheduled_trigger') return `Every ${config.interval_minutes} minutes`
  return spec.description
}

export function StepNode({ data, selected }: NodeProps<StepNodeType>) {
  const outputs = outputsOf(data.spec)
  return (
    <div
      className={cn(
        'w-56 rounded-lg border bg-surface px-3 pt-2 pb-5 text-left shadow-sm',
        selected ? 'border-primary ring-2 ring-primary/30' : 'border-border',
        data.problem && 'border-danger',
      )}
    >
      {!data.spec.trigger && <Handle type="target" position={Position.Top} className="!size-2.5 !bg-muted" />}
      <p className="text-[10px] font-medium tracking-wide text-muted uppercase">{data.spec.category}</p>
      <p className="text-sm font-medium text-foreground">{data.spec.label}</p>
      <p className="mt-0.5 line-clamp-2 text-[11px] text-muted">{summary(data.spec, data.config)}</p>
      {outputs.map((handle, index) => {
        const left = `${((index + 1) / (outputs.length + 1)) * 100}%`
        return (
          <div key={handle}>
            <Handle
              id={handle}
              type="source"
              position={Position.Bottom}
              style={{ left }}
              className={cn('!size-2.5', handle === 'error' ? '!bg-danger' : handle === 'false' ? '!bg-warning' : '!bg-primary')}
            />
            {outputs.length > 1 && (
              <span className="absolute bottom-1 -translate-x-1/2 text-[9px] text-muted" style={{ left }}>
                {HANDLE_LABELS[handle]}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
