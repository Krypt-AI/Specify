import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type { ClassificationUpdate, EmailDetail, EmailFilters, EmailPage, EmailStats } from './types'

export const emailKeys = {
  all: ['emails'] as const,
  list: (filters: EmailFilters) => ['emails', 'list', filters] as const,
  detail: (id: string) => ['emails', 'detail', id] as const,
  stats: ['emails', 'stats'] as const,
}

function toQuery(filters: EmailFilters) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return params.toString()
}

export function useEmails(filters: EmailFilters) {
  return useQuery({
    queryKey: emailKeys.list(filters),
    queryFn: () => apiRequest<EmailPage>(`/emails?${toQuery(filters)}`),
    placeholderData: keepPreviousData,
  })
}

export function useEmail(id: string | null) {
  return useQuery({
    queryKey: emailKeys.detail(id ?? ''),
    queryFn: () => apiRequest<EmailDetail>(`/emails/${id}`),
    enabled: id !== null,
  })
}

export function useEmailStats() {
  return useQuery({ queryKey: emailKeys.stats, queryFn: () => apiRequest<EmailStats>('/emails/stats') })
}

function useEmailMutation<TVariables>(request: (variables: TVariables) => Promise<EmailDetail>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: (email) => {
      queryClient.setQueryData(emailKeys.detail(email.id), email)
      queryClient.invalidateQueries({ queryKey: emailKeys.all })
      queryClient.invalidateQueries({ queryKey: ['labels'] })
    },
  })
}

export function useUpdateClassification(id: string) {
  return useEmailMutation((body: ClassificationUpdate) =>
    apiRequest<EmailDetail>(`/emails/${id}/classification`, { method: 'PATCH', body: JSON.stringify(body) }),
  )
}

export function useReprocessEmail(id: string) {
  return useEmailMutation(() => apiRequest<EmailDetail>(`/emails/${id}/reprocess`, { method: 'POST' }))
}
