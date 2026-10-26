import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '@/lib/api'

import type { Rule, RuleInput, RuleSuggestion } from './types'

const ruleKeys = { all: ['rules'] as const, suggestions: ['rules', 'suggestions'] as const }

export function useRules() {
  return useQuery({ queryKey: ruleKeys.all, queryFn: () => apiRequest<Rule[]>('/rules') })
}

export function useRuleSuggestions() {
  return useQuery({ queryKey: ruleKeys.suggestions, queryFn: () => apiRequest<RuleSuggestion[]>('/rules/suggestions') })
}

function useRuleMutation<TVariables, TResult>(request: (variables: TVariables) => Promise<TResult>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ruleKeys.all }),
  })
}

export function useCreateRule() {
  return useRuleMutation((rule: RuleInput) => apiRequest<Rule>('/rules', { method: 'POST', body: JSON.stringify(rule) }))
}

export function useUpdateRule() {
  return useRuleMutation(({ id, ...changes }: Partial<RuleInput> & { id: string }) =>
    apiRequest<Rule>(`/rules/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  )
}

export function useDeleteRule() {
  return useRuleMutation((id: string) => apiRequest<void>(`/rules/${id}`, { method: 'DELETE' }))
}
