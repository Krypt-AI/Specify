import type { DecisionName, OpportunityDetail, OpportunityStatus, OpportunitySummary } from '@/api/types'

type Tone = 'neutral' | 'success' | 'warning' | 'danger'

export const STATUS_INFO: Record<OpportunityStatus, { label: string; tone: Tone }> = {
  new: { label: 'New', tone: 'warning' },
  awaiting_decision: { label: 'Awaiting decision', tone: 'warning' },
  interested: { label: 'Interested', tone: 'success' },
  more_info_required: { label: 'More info required', tone: 'neutral' },
  preparing_application: { label: 'Preparing application', tone: 'neutral' },
  applied: { label: 'Applied', tone: 'success' },
  interview_scheduled: { label: 'Interview scheduled', tone: 'success' },
  interview_completed: { label: 'Interview completed', tone: 'success' },
  offer_received: { label: 'Offer received', tone: 'success' },
  offer_accepted: { label: 'Offer accepted', tone: 'success' },
  offer_declined: { label: 'Offer declined', tone: 'neutral' },
  rejected: { label: 'Rejected', tone: 'danger' },
  withdrawn: { label: 'Withdrawn', tone: 'neutral' },
  archived: { label: 'Archived', tone: 'neutral' },
}

export const STATUSES = Object.keys(STATUS_INFO) as OpportunityStatus[]

export const DECISIONS: { value: DecisionName; label: string; description: string }[] = [
  { value: 'interested', label: 'Interested', description: 'You want to go ahead.' },
  { value: 'interested_need_info', label: 'Interested, need more information', description: 'Keen, with open questions.' },
  { value: 'request_salary', label: 'Request salary details', description: 'Ask for the range and benefits.' },
  { value: 'request_job_description', label: 'Request job description', description: 'Ask for the full role details.' },
  { value: 'request_interview_details', label: 'Request interview details', description: 'Ask about format, time and people.' },
  { value: 'request_more_time', label: 'Request more time', description: 'Ask for an extension. Back in your queue in 3 days.' },
  { value: 'decline', label: 'Decline', description: 'Close the opportunity politely.' },
  { value: 'already_applied', label: 'Already applied', description: 'You applied already.' },
  { value: 'save_for_later', label: 'Save for later', description: 'Back in your queue in 7 days.' },
  { value: 'irrelevant', label: 'Mark as irrelevant', description: 'Archive it.' },
  { value: 'custom', label: 'Custom decision', description: 'Describe it yourself.' },
]

export const DECISION_LABELS = Object.fromEntries(DECISIONS.map((d) => [d.value, d.label])) as Record<DecisionName, string>

export const MISSING_LABELS: Record<OpportunityDetail['missing_information'][number], string> = {
  salary: 'Salary',
  job_description: 'Job description',
  work_arrangement: 'Remote, hybrid or on-site',
  location: 'Location',
}

export function formatSalary(o: Pick<OpportunitySummary, 'salary_min' | 'salary_max' | 'salary_currency' | 'salary_period'>) {
  if (o.salary_min === null && o.salary_max === null) return null
  const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  const range =
    o.salary_min !== null && o.salary_max !== null && o.salary_min !== o.salary_max
      ? `${number(o.salary_min)}–${number(o.salary_max)}`
      : number((o.salary_min ?? o.salary_max)!)
  return [o.salary_currency, range, o.salary_period && `per ${o.salary_period}`].filter(Boolean).join(' ')
}
