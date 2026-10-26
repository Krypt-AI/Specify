import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type {
  ActivityEvent,
  NodeTypeSpec,
  RunStatus,
  Workflow,
  WorkflowGraph,
  WorkflowRunDetail,
  WorkflowRunSummary,
  WorkflowTemplate,
} from './types'

const keys = {
  all: ['workflows'] as const,
  detail: (id: string) => ['workflows', id] as const,
  nodeTypes: ['workflows', 'node-types'] as const,
  templates: ['workflows', 'templates'] as const,
  runs: (filters: object) => ['workflow-runs', filters] as const,
  run: (id: string) => ['workflow-runs', 'detail', id] as const,
  activity: (action: string) => ['activity', action] as const,
}

const ACTIVE: RunStatus[] = ['running', 'retrying']

export function useNodeTypes() {
  return useQuery({ queryKey: keys.nodeTypes, queryFn: () => apiRequest<NodeTypeSpec[]>('/workflows/node-types'), staleTime: Infinity })
}

export function useWorkflows() {
  return useQuery({ queryKey: keys.all, queryFn: () => apiRequest<Workflow[]>('/workflows') })
}

export function useWorkflow(id: string) {
  return useQuery({ queryKey: keys.detail(id), queryFn: () => apiRequest<Workflow>(`/workflows/${id}`) })
}

export function useWorkflowTemplates() {
  return useQuery({ queryKey: keys.templates, queryFn: () => apiRequest<WorkflowTemplate[]>('/workflows/templates') })
}

export function useRuns(filters: { workflow_id?: string; status?: string }) {
  const params = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][])
  return useQuery({
    queryKey: keys.runs(filters),
    queryFn: () => apiRequest<WorkflowRunSummary[]>(`/workflows/runs?${params}`),
    refetchInterval: (query) => (query.state.data?.some((r) => ACTIVE.includes(r.status)) ? 3000 : false),
  })
}

export function useRun(id: string | null) {
  return useQuery({
    queryKey: keys.run(id ?? ''),
    queryFn: () => apiRequest<WorkflowRunDetail>(`/workflows/runs/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data && ACTIVE.includes(query.state.data.status) ? 2000 : false),
  })
}

export function useActivity(action: string) {
  return useQuery({
    queryKey: keys.activity(action),
    queryFn: () => apiRequest<ActivityEvent[]>(`/activity?limit=200${action ? `&action=${encodeURIComponent(action)}` : ''}`),
  })
}

function useWorkflowMutation<TVariables, TResult>(request: (variables: TVariables) => Promise<TResult>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.all })
      queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
    },
  })
}

export function useCreateWorkflow() {
  return useWorkflowMutation((body: { name: string; template?: string }) =>
    apiRequest<Workflow>('/workflows', { method: 'POST', body: JSON.stringify(body) }),
  )
}

export function useSaveWorkflow(id: string) {
  return useWorkflowMutation((body: { name: string; description: string; definition_json: WorkflowGraph }) =>
    apiRequest<Workflow>(`/workflows/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  )
}

export function useSetWorkflowEnabled(id: string) {
  return useWorkflowMutation((enabled: boolean) =>
    apiRequest<Workflow>(`/workflows/${id}/enabled`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  )
}

export function useWorkflowCopy(id: string) {
  return useWorkflowMutation((kind: 'duplicate' | 'save-template') => apiRequest<Workflow>(`/workflows/${id}/${kind}`, { method: 'POST' }))
}

export function useDeleteWorkflow() {
  return useWorkflowMutation((id: string) => apiRequest<void>(`/workflows/${id}`, { method: 'DELETE' }))
}

export function useTestRun(id: string) {
  return useWorkflowMutation((emailId: string | null) =>
    apiRequest<WorkflowRunSummary>(`/workflows/${id}/test`, { method: 'POST', body: JSON.stringify({ email_id: emailId }) }),
  )
}

export function useRunAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'retry' | 'cancel' | 'pause' | 'resume' | 'approve' | 'reject' }) =>
      apiRequest<WorkflowRunDetail>(`/workflows/runs/${id}/${action}`, { method: 'POST' }),
    onSuccess: (run) => {
      queryClient.setQueryData(keys.run(run.id), run)
      queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
    },
  })
}
