import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, apiRequest } from '@/lib/api'

import type {
  CompanyDetail,
  Company,
  Contact,
  DecisionName,
  DuplicateCandidate,
  OpportunityDetail,
  OpportunityFields,
  OpportunityFilters,
  OpportunityPage,
  OpportunityStats,
  OpportunityStatus,
} from './types'

const keys = {
  opportunities: ['opportunities'] as const,
  list: (filters: OpportunityFilters) => ['opportunities', 'list', filters] as const,
  detail: (id: string) => ['opportunities', 'detail', id] as const,
  stats: ['opportunities', 'stats'] as const,
  companies: ['companies'] as const,
  company: (id: string) => ['companies', id] as const,
  duplicates: ['duplicates'] as const,
}

function toQuery(filters: Record<string, unknown>) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '' && value !== false) params.set(key, String(value))
  }
  return params.toString()
}

/**
 * Runs a request that the server may refuse with 409 for consequential changes; asks the user
 * and repeats it with confirmation. Resolves to undefined when the user cancels.
 */
export async function withConfirmation<T>(run: (confirm: boolean) => Promise<T>): Promise<T | undefined> {
  try {
    return await run(false)
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && window.confirm(error.message)) return run(true)
    if (error instanceof ApiError && error.status === 409) return undefined
    throw error
  }
}

function useInvalidateRecruitment() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: keys.opportunities })
    queryClient.invalidateQueries({ queryKey: keys.companies })
    queryClient.invalidateQueries({ queryKey: keys.duplicates })
    queryClient.invalidateQueries({ queryKey: ['emails'] })
  }
}

export function useOpportunities(filters: OpportunityFilters) {
  return useQuery({
    queryKey: keys.list(filters),
    queryFn: () => apiRequest<OpportunityPage>(`/opportunities?${toQuery(filters)}`),
    placeholderData: keepPreviousData,
  })
}

export function useOpportunity(id: string | null) {
  return useQuery({
    queryKey: keys.detail(id ?? ''),
    queryFn: () => apiRequest<OpportunityDetail>(`/opportunities/${id}`),
    enabled: id !== null,
  })
}

export function useOpportunityStats() {
  return useQuery({ queryKey: keys.stats, queryFn: () => apiRequest<OpportunityStats>('/opportunities/stats') })
}

export function useCreateOpportunity() {
  const invalidate = useInvalidateRecruitment()
  return useMutation({
    mutationFn: (body: OpportunityFields & { job_title: string; company_name?: string; from_email_id?: string }) =>
      apiRequest<OpportunityDetail>('/opportunities', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: invalidate,
  })
}

export function useUpdateOpportunity(id: string) {
  const invalidate = useInvalidateRecruitment()
  return useMutation({
    mutationFn: (changes: OpportunityFields & { status?: OpportunityStatus }) =>
      withConfirmation((confirm) =>
        apiRequest<OpportunityDetail>(`/opportunities/${id}`, {
          method: 'PATCH',
          body: JSON.stringify({ ...changes, confirm }),
        }),
      ),
    onSuccess: invalidate,
  })
}

export function useRecordDecision(id: string) {
  const invalidate = useInvalidateRecruitment()
  return useMutation({
    mutationFn: (body: { decision: DecisionName; notes?: string; custom_decision?: string; email_id?: string }) =>
      withConfirmation((confirm) =>
        apiRequest<OpportunityDetail>(`/opportunities/${id}/decision`, {
          method: 'POST',
          body: JSON.stringify({ ...body, confirm }),
        }),
      ),
    onSuccess: invalidate,
  })
}

export function useCompanies(q: string) {
  return useQuery({
    queryKey: [...keys.companies, 'list', q],
    queryFn: () => apiRequest<{ items: Company[]; total: number }>(`/companies?${toQuery({ q })}`),
    placeholderData: keepPreviousData,
  })
}

export function useCompany(id: string | null) {
  return useQuery({
    queryKey: keys.company(id ?? ''),
    queryFn: () => apiRequest<CompanyDetail>(`/companies/${id}`),
    enabled: id !== null,
  })
}

export function useUpdateCompany(id: string) {
  const invalidate = useInvalidateRecruitment()
  return useMutation({
    mutationFn: (changes: Partial<Omit<Company, 'id' | 'opportunity_count' | 'contact_count'>>) =>
      apiRequest<CompanyDetail>(`/companies/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
    onSuccess: invalidate,
  })
}

export function useUpdateContact() {
  const invalidate = useInvalidateRecruitment()
  return useMutation({
    mutationFn: ({ id, ...changes }: Partial<Contact> & { id: string }) =>
      apiRequest<Contact>(`/contacts/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
    onSuccess: invalidate,
  })
}

export function useDuplicates() {
  return useQuery({ queryKey: keys.duplicates, queryFn: () => apiRequest<DuplicateCandidate[]>('/duplicates') })
}

export function useResolveDuplicate() {
  const invalidate = useInvalidateRecruitment()
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'merge' | 'dismiss' }) =>
      apiRequest<void>(`/duplicates/${id}/${action}`, { method: 'POST' }),
    onSuccess: invalidate,
  })
}
