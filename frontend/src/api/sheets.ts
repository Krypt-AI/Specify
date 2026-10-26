import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type { SheetConflict, SheetsSettings, SheetsStatus, SyncJob } from './types'

const keys = { status: ['sheets'] as const, jobs: ['sheets', 'jobs'] as const, conflicts: ['sheets', 'conflicts'] as const }

const isActive = (job?: SyncJob | null) => job?.status === 'queued' || job?.status === 'running'

function useInvalidateSheets() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: keys.status })
}

export function useSheets() {
  return useQuery({ queryKey: keys.status, queryFn: () => apiRequest<SheetsStatus>('/sheets') })
}

export function useSyncJobs(enabled: boolean) {
  const invalidate = useInvalidateSheets()
  return useQuery({
    queryKey: keys.jobs,
    queryFn: async () => {
      const jobs = await apiRequest<SyncJob[]>('/sheets/jobs')
      if (!isActive(jobs[0])) invalidate()
      return jobs
    },
    enabled,
    refetchInterval: (query) => (isActive(query.state.data?.[0]) ? 3000 : false),
  })
}

export function useSheetConflicts(enabled: boolean) {
  return useQuery({ queryKey: keys.conflicts, queryFn: () => apiRequest<SheetConflict[]>('/sheets/conflicts'), enabled })
}

function useSheetsMutation<TVariables, TResult>(request: (variables: TVariables) => Promise<TResult>) {
  const invalidate = useInvalidateSheets()
  return useMutation({ mutationFn: request, onSuccess: invalidate })
}

export function useSelectSpreadsheet() {
  return useSheetsMutation((spreadsheet: string) =>
    apiRequest<SheetsStatus>('/sheets/spreadsheet', { method: 'POST', body: JSON.stringify({ spreadsheet }) }),
  )
}

export function useCreateSpreadsheet() {
  return useSheetsMutation((title: string) =>
    apiRequest<SheetsStatus>('/sheets/spreadsheet/create', { method: 'POST', body: JSON.stringify({ title }) }),
  )
}

export function useRemoveSpreadsheet() {
  return useSheetsMutation(() => apiRequest<void>('/sheets/spreadsheet', { method: 'DELETE' }))
}

export function useSaveSheetsSettings() {
  return useSheetsMutation((settings: SheetsSettings) =>
    apiRequest<SheetsStatus>('/sheets/settings', { method: 'PUT', body: JSON.stringify(settings) }),
  )
}

export function useSyncSheets() {
  return useSheetsMutation(() => apiRequest<SyncJob>('/sheets/sync', { method: 'POST' }))
}

export function useRetrySync() {
  return useSheetsMutation((jobId: string) => apiRequest<SyncJob>(`/sheets/jobs/${jobId}/retry`, { method: 'POST' }))
}

export function useResolveConflict() {
  return useSheetsMutation(({ id, resolution }: { id: string; resolution: string }) =>
    apiRequest<void>(`/sheets/conflicts/${id}/resolve`, { method: 'POST', body: JSON.stringify({ resolution }) }),
  )
}
