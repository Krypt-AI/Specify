import type { DraftTone } from '@/api/types'

export const DRAFT_TONES: { value: DraftTone; label: string }[] = [
  { value: 'formal', label: 'Formal' },
  { value: 'friendly', label: 'Friendly and professional' },
  { value: 'concise', label: 'Concise' },
  { value: 'enthusiastic', label: 'Enthusiastic' },
]

export const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone

export const TIMEZONES: string[] = Intl.supportedValuesOf('timeZone')
