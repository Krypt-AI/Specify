import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type { SyncStatus } from './types'

const syncKeys = { gmail: ['sync', 'gmail'] as const }

const isBusy = (status: SyncStatus) => status.status === 'running' || status.queued_emails > 0

export function useSyncStatus() {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: syncKeys.gmail,
    queryFn: async () => {
      const previous = queryClient.getQueryData<SyncStatus>(syncKeys.gmail)
      const status = await apiRequest<SyncStatus>('/sync/gmail')
      if (previous && isBusy(previous) && !isBusy(status)) {
        queryClient.invalidateQueries({ queryKey: ['emails'] })  // work just finished
      }
      return status
    },
    // Poll only while a sync is running or emails are still being classified.
    refetchInterval: (query) => (query.state.data && isBusy(query.state.data) ? 3000 : false),
  })
}

export function useTriggerSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiRequest<{ status: string }>('/sync/gmail', { method: 'POST' }),
    onSuccess: () => {
      queryClient.setQueryData<SyncStatus>(syncKeys.gmail, (current) => current && { ...current, status: 'running' })
    },
  })
}
