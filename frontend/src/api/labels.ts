import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type { Label } from './types'

const labelKeys = { all: ['labels'] as const }

export function useLabels() {
  return useQuery({ queryKey: labelKeys.all, queryFn: () => apiRequest<Label[]>('/labels') })
}

export function useCreateLabel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) =>
      apiRequest<Label>('/labels', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: labelKeys.all }),
  })
}

export function useUpdateLabel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; description?: string; enabled?: boolean }) =>
      apiRequest<Label>(`/labels/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: labelKeys.all })
      queryClient.invalidateQueries({ queryKey: ['emails'] })
    },
  })
}
