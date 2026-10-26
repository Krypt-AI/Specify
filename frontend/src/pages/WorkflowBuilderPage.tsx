import '@xyflow/react/dist/style.css'

import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
} from '@xyflow/react'
import { ArrowLeft, Copy, FlaskConical, Save } from 'lucide-react'
import { useMemo, useState, type DragEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useEmails } from '@/api/emails'
import type { NodeTypeSpec, Workflow, WorkflowGraph } from '@/api/types'
import {
  useNodeTypes,
  useRuns,
  useSaveWorkflow,
  useSetWorkflowEnabled,
  useTestRun,
  useWorkflow,
  useWorkflowCopy,
} from '@/api/workflows'
import { NodeInspector } from '@/components/workflows/NodeInspector'
import { StepNode, type StepNodeType } from '@/components/workflows/StepNode'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { fieldClass } from '@/components/ui/field'
import { Toggle } from '@/components/ui/toggle'
import { HANDLE_LABELS, RUN_STATUS } from '@/lib/workflows'
import { cn, formatShortDate } from '@/lib/utils'

const NODE_TYPES = { step: StepNode }
const DRAG_TYPE = 'application/specify-step'

export function WorkflowBuilderPage() {
  const { id = '' } = useParams()
  const { data: workflow } = useWorkflow(id)
  const { data: specs } = useNodeTypes()
  if (!workflow || !specs) return <p className="text-sm text-muted">Loading workflow…</p>
  return (
    <ReactFlowProvider>
      <Builder key={`${workflow.id}-${workflow.version}`} workflow={workflow} specs={specs} />
    </ReactFlowProvider>
  )
}

function toFlow(graph: WorkflowGraph, specs: Record<string, NodeTypeSpec>, problemIds: Set<string>) {
  const nodes: StepNodeType[] = graph.nodes
    .filter((n) => specs[n.type])
    .map((n) => ({
      id: n.id,
      type: 'step',
      position: n.position,
      data: { spec: specs[n.type], config: { ...specs[n.type].defaults, ...n.config }, problem: problemIds.has(n.id) },
    }))
  const edges: Edge[] = graph.edges.map((e) => edge(e.source, e.target, e.handle))
  return { nodes, edges }
}

function edge(source: string, target: string, handle: string): Edge {
  return {
    id: `${source}-${handle}-${target}`,
    source,
    target,
    sourceHandle: handle,
    label: handle === 'out' ? undefined : HANDLE_LABELS[handle],
    style: handle === 'error' ? { stroke: 'var(--color-danger)' } : undefined,
  }
}

function Builder({ workflow, specs: specList }: { workflow: Workflow; specs: NodeTypeSpec[] }) {
  const specs = useMemo(() => Object.fromEntries(specList.map((s) => [s.key, s])), [specList])
  const problemIds = useMemo(() => new Set(workflow.problems.map((p) => p.split(':')[0])), [workflow.problems])
  const initial = useMemo(() => toFlow(workflow.definition_json, specs, problemIds), [workflow, specs, problemIds])
  const [nodes, setNodes, onNodesChange] = useNodesState<StepNodeType>(initial.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initial.edges)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [name, setName] = useState(workflow.name)
  const flow = useReactFlow()
  const navigate = useNavigate()
  const save = useSaveWorkflow(workflow.id)
  const setEnabled = useSetWorkflowEnabled(workflow.id)
  const copy = useWorkflowCopy(workflow.id)

  const graph = (): WorkflowGraph => ({
    nodes: nodes.map((n) => ({ id: n.id, type: n.data.spec.key, config: n.data.config, position: n.position })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, handle: e.sourceHandle ?? 'out' })),
  })
  const dirty = JSON.stringify(graph()) !== JSON.stringify(toFlowGraph(initial)) || name !== workflow.name

  const onConnect = (connection: Connection) => {
    const handle = connection.sourceHandle ?? 'out'
    // One connection per output: replace an existing one.
    setEdges((current) =>
      addEdge(edge(connection.source, connection.target, handle), current.filter((e) => !(e.source === connection.source && (e.sourceHandle ?? 'out') === handle))),
    )
  }

  const addStep = (type: string, position = flow.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })) => {
    const spec = specs[type]
    let index = 1
    while (nodes.some((n) => n.id === `${type}_${index}`)) index += 1
    const id = `${type}_${index}`
    setNodes((current) => [...current, { id, type: 'step', position, data: { spec, config: { ...spec.defaults }, problem: false } }])
    setSelectedId(id)
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    const type = event.dataTransfer.getData(DRAG_TYPE)
    if (type) addStep(type, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }))
  }

  const selected = nodes.find((n) => n.id === selectedId)
  const updateConfig = (config: Record<string, unknown>) =>
    setNodes((current) => current.map((n) => (n.id === selectedId ? { ...n, data: { ...n.data, config } } : n)))
  const removeSelected = () => {
    setNodes((current) => current.filter((n) => n.id !== selectedId))
    setEdges((current) => current.filter((e) => e.source !== selectedId && e.target !== selectedId))
    setSelectedId(null)
  }
  const categories = Object.entries(
    specList.reduce<Record<string, NodeTypeSpec[]>>((groups, spec) => ({ ...groups, [spec.category]: [...(groups[spec.category] ?? []), spec] }), {}),
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/workflows" className="text-muted" aria-label="Back to workflows">
          <ArrowLeft className="size-5" />
        </Link>
        <input className={cn(fieldClass, 'mt-0 max-w-xs font-medium')} value={name} onChange={(e) => setName(e.target.value)} aria-label="Workflow name" />
        {workflow.is_default && <Badge>Default</Badge>}
        <Button onClick={() => save.mutate({ name, description: workflow.description, definition_json: graph() })} disabled={save.isPending || !dirty}>
          <Save className="size-4" aria-hidden /> Save
        </Button>
        <div className="w-40">
          <Toggle
            checked={workflow.enabled}
            onChange={(enabled) => setEnabled.mutate(enabled)}
            label={workflow.enabled ? 'Enabled' : 'Disabled'}
            disabled={dirty || setEnabled.isPending}
          />
        </div>
        <TestRunButton workflow={workflow} disabled={dirty} />
        <Button variant="ghost" onClick={() => copy.mutate('duplicate', { onSuccess: (w) => navigate(`/workflows/${w.id}`) })}>
          <Copy className="size-4" aria-hidden /> Duplicate
        </Button>
        <Button variant="ghost" onClick={() => copy.mutate('save-template')}>
          Save as template
        </Button>
        {dirty && <span className="text-xs text-warning">Unsaved changes</span>}
      </div>
      {(setEnabled.error || save.error) && <p className="text-sm text-danger">{(setEnabled.error ?? save.error)?.message}</p>}
      {workflow.problems.length > 0 && (
        <Card className="border-danger/40 py-3">
          <p className="text-sm font-medium text-danger">This workflow cannot run until these are fixed:</p>
          <ul className="mt-1 list-disc pl-5 text-sm">
            {workflow.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-3 lg:grid-cols-[12rem_minmax(0,1fr)_18rem]">
        <Card className="max-h-[70vh] overflow-y-auto p-3">
          <p className="mb-2 text-xs text-muted">Drag a step onto the canvas, or click to add it.</p>
          {categories.map(([category, items]) => (
            <div key={category} className="mb-3">
              <p className="mb-1 text-[11px] font-medium tracking-wide text-muted uppercase">{category}</p>
              {items.map((spec) => (
                <button
                  key={spec.key}
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData(DRAG_TYPE, spec.key)}
                  onClick={() => addStep(spec.key)}
                  title={spec.description}
                  className="mb-1 block w-full rounded-md border border-border bg-background px-2 py-1.5 text-left text-xs hover:border-primary"
                >
                  {spec.label}
                </button>
              ))}
            </div>
          ))}
        </Card>
        <div className="h-[70vh] overflow-hidden rounded-lg border border-border" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
            colorMode={document.documentElement.classList.contains('dark') ? 'dark' : 'light'}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        <Card className="max-h-[70vh] overflow-y-auto">
          {selected ? (
            <NodeInspector
              key={selected.id}
              nodeId={selected.id}
              spec={selected.data.spec}
              config={selected.data.config}
              problems={workflow.problems.filter((p) => p.startsWith(`${selected.id}:`))}
              onChange={updateConfig}
              onDelete={removeSelected}
            />
          ) : (
            <RunHistory workflowId={workflow.id} />
          )}
        </Card>
      </div>
    </div>
  )
}

function toFlowGraph(initial: { nodes: StepNodeType[]; edges: Edge[] }): WorkflowGraph {
  return {
    nodes: initial.nodes.map((n) => ({ id: n.id, type: n.data.spec.key, config: n.data.config, position: n.position })),
    edges: initial.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, handle: e.sourceHandle ?? 'out' })),
  }
}

function TestRunButton({ workflow, disabled }: { workflow: Workflow; disabled: boolean }) {
  const [open, setOpen] = useState(false)
  const [emailId, setEmailId] = useState('')
  const { data: emails } = useEmails({ page_size: 20 })
  const test = useTestRun(workflow.id)
  const navigate = useNavigate()
  const needsEmail = workflow.trigger_type === 'gmail_new_email'

  if (!open) {
    return (
      <Button variant="outline" onClick={() => setOpen(true)} disabled={disabled || workflow.problems.length > 0}>
        <FlaskConical className="size-4" aria-hidden /> Test run
      </Button>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2">
      {needsEmail && (
        <select className={cn(fieldClass, 'mt-0 max-w-xs')} value={emailId} onChange={(e) => setEmailId(e.target.value)} aria-label="Email to test with">
          <option value="">Choose an email…</option>
          {emails?.items.map((email) => (
            <option key={email.id} value={email.id}>
              {email.subject || '(no subject)'} · {email.sender_email}
            </option>
          ))}
        </select>
      )}
      <Button
        disabled={(needsEmail && !emailId) || test.isPending}
        onClick={() => test.mutate(emailId || null, { onSuccess: (run) => navigate(`/activity?run=${run.id}`) })}
      >
        Run without changing anything
      </Button>
      <Button variant="ghost" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      {test.isError && <span className="text-sm text-danger">{test.error.message}</span>}
    </div>
  )
}

function RunHistory({ workflowId }: { workflowId: string }) {
  const { data: runs = [] } = useRuns({ workflow_id: workflowId })
  return (
    <div className="space-y-2">
      <h3 className="font-semibold">Recent runs</h3>
      <p className="text-xs text-muted">Select a step on the canvas to edit it.</p>
      {runs.length === 0 && <p className="text-sm text-muted">No runs yet.</p>}
      <ul className="space-y-1 text-sm">
        {runs.slice(0, 15).map((run) => (
          <li key={run.id}>
            <Link to={`/activity?run=${run.id}`} className="flex items-center gap-2 hover:underline">
              <Badge tone={RUN_STATUS[run.status].tone}>{RUN_STATUS[run.status].label}</Badge>
              <span className="truncate text-xs text-muted">
                {run.is_test ? 'Test · ' : ''}
                {formatShortDate(run.created_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
