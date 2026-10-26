import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type { Analytics, AppNotification, DashboardSummary, FollowUp } from './types'

const keys = {
  followUps: (status: string) => ['follow-ups', status] as const,
  notifications: ['notifications'] as const,
  analytics: (days: number) => ['analytics', days] as const,
  summary: ['analytics', 'summary'] as const,
}

export function useFollowUps(status: 'open' | 'done' | 'all') {
  return useQuery({ queryKey: keys.followUps(status), queryFn: () => apiRequest<FollowUp[]>(`/follow-ups?status=${status}`) })
}

function useFollowUpMutation<TVariables>(request: (variables: TVariables) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['follow-ups'] })
      queryClient.invalidateQueries({ queryKey: keys.summary })
    },
  })
}

export function useCreateFollowUp() {
  return useFollowUpMutation((body: { title: string; due_at: string; notes?: string; opportunity_id?: string }) =>
    apiRequest<FollowUp>('/follow-ups', { method: 'POST', body: JSON.stringify(body) }),
  )
}

export function useFollowUpAction() {
  return useFollowUpMutation(({ id, action, until }: { id: string; action: 'complete' | 'reopen' | 'snooze' | 'cancel'; until?: string }) =>
    action === 'cancel'
      ? apiRequest<void>(`/follow-ups/${id}`, { method: 'DELETE' })
      : apiRequest<FollowUp>(`/follow-ups/${id}/${action}`, { method: 'POST', body: until ? JSON.stringify({ until }) : undefined }),
  )
}

export function useNotifications() {
  return useQuery({
    queryKey: keys.notifications,
    queryFn: () => apiRequest<{ items: AppNotification[]; unread: number }>('/notifications'),
    refetchInterval: 60_000,
  })
}

export function useMarkNotifications() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string | 'all') =>
      apiRequest<void>(id === 'all' ? '/notifications/read-all' : `/notifications/${id}/read`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.notifications }),
  })
}

export function useAnalytics(days: number) {
  return useQuery({ queryKey: keys.analytics(days), queryFn: () => apiRequest<Analytics>(`/analytics?days=${days}`) })
}

export function useDashboardSummary() {
  return useQuery({ queryKey: keys.summary, queryFn: () => apiRequest<DashboardSummary>('/analytics/summary') })
}
