import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type { Draft, DraftTemplate } from './types'

const keys = {
  all: ['drafts'] as const,
  list: (status: string) => ['drafts', 'list', status] as const,
  detail: (id: string) => ['drafts', 'detail', id] as const,
  templates: ['drafts', 'templates'] as const,
}

export function useDrafts(status: string) {
  return useQuery({
    queryKey: keys.list(status),
    queryFn: () => apiRequest<Draft[]>(`/drafts${status ? `?status=${status}` : ''}`),
    // Keep the list fresh while any draft is still being written.
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === 'generating') ? 3000 : false),
  })
}

export function useDraft(id: string | null) {
  return useQuery({
    queryKey: keys.detail(id ?? ''),
    queryFn: () => apiRequest<Draft>(`/drafts/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data?.status === 'generating' ? 2000 : false),
  })
}

function useDraftMutation<TVariables>(request: (variables: TVariables) => Promise<Draft | void>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: (draft) => {
      if (draft) queryClient.setQueryData(keys.detail(draft.id), draft)
      queryClient.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useUpdateDraft(id: string) {
  return useDraftMutation((changes: { subject?: string; body?: string }) =>
    apiRequest<Draft>(`/drafts/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  )
}

export function useRegenerateDraft(id: string) {
  return useDraftMutation((options: { tone?: string; instructions?: string }) =>
    apiRequest<Draft>(`/drafts/${id}/regenerate`, { method: 'POST', body: JSON.stringify(options) }),
  )
}

export function useSaveDraftToGmail(id: string) {
  return useDraftMutation(() => apiRequest<Draft>(`/drafts/${id}/gmail`, { method: 'POST' }))
}

export function useDiscardDraft(id: string) {
  return useDraftMutation(() => apiRequest<void>(`/drafts/${id}`, { method: 'DELETE' }))
}

export function useRequestReply(emailId: string) {
  return useDraftMutation((options: { scenario?: string; tone?: string; instructions?: string }) =>
    apiRequest<Draft>(`/emails/${emailId}/drafts`, { method: 'POST', body: JSON.stringify(options) }),
  )
}

export function useDraftTemplates() {
  return useQuery({ queryKey: keys.templates, queryFn: () => apiRequest<DraftTemplate[]>('/drafts/templates') })
}

export function useSaveTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ scenario, ...body }: Pick<DraftTemplate, 'scenario' | 'instructions' | 'body' | 'use_ai'>) =>
      apiRequest<DraftTemplate>(`/drafts/templates/${scenario}`, { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.templates }),
  })
}

export function useResetTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (scenario: string) => apiRequest<void>(`/drafts/templates/${scenario}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.templates }),
  })
}
