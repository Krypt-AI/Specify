import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { API_URL, ApiError, apiRequest } from '@/lib/api'

import type { DeepPartial, IntegrationProvider, IntegrationStatus, Preferences, User } from './types'

export const accountKeys = {
  me: ['me'] as const,
  integrations: ['integrations'] as const,
}

export function useCurrentUser() {
  return useQuery({
    queryKey: accountKeys.me,
    queryFn: async () => {
      try {
        return await apiRequest<User>('/auth/me')
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
  })
}

/** The user's display timezone; undefined falls back to the browser's. */
export function useTimezone() {
  return useCurrentUser().data?.preferences.timezone ?? undefined
}

export function useIntegrations() {
  return useQuery({
    queryKey: accountKeys.integrations,
    queryFn: () => apiRequest<IntegrationStatus[]>('/integrations'),
  })
}

export function useDisconnectIntegration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (provider: IntegrationProvider) =>
      apiRequest<void>(`/integrations/${provider}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: accountKeys.integrations }),
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { preferences: DeepPartial<Preferences>; setup_completed?: boolean }) =>
      apiRequest<User>('/settings', { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: (user) => queryClient.setQueryData(accountKeys.me, user),
  })
}

/** Downloads everything Specify stores about the user as a JSON file. */
export function useExportAccount() {
  return useMutation({
    mutationFn: async () => {
      const response = await fetch(`${API_URL}/api/account/export`, { credentials: 'include' })
      if (!response.ok) throw new ApiError(response.status, 'The export could not be created. Please try again.')
      const filename = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? 'specify-export.json'
      const url = URL.createObjectURL(await response.blob())
      Object.assign(document.createElement('a'), { href: url, download: filename }).click()
      URL.revokeObjectURL(url)
    },
  })
}

export function useDeleteAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (confirmEmail: string) =>
      apiRequest<void>('/account', { method: 'DELETE', body: JSON.stringify({ confirm_email: confirmEmail }) }),
    onSuccess: () => {
      queryClient.clear()
      queryClient.setQueryData(accountKeys.me, null)
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiRequest<void>('/auth/logout', { method: 'POST' }),
    onSuccess: () => queryClient.setQueryData(accountKeys.me, null),
  })
}
