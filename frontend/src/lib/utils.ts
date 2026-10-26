import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDateTime(value: string | null, timeZone?: string) {
  if (!value) return 'Never'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone,
  }).format(new Date(value))
}

/** Time for today, day and month for this year, full date otherwise. */
export function formatShortDate(value: string, timeZone?: string) {
  const date = new Date(value)
  const dayKey = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone }).format(d)
  const yearOf = (d: Date) => new Intl.DateTimeFormat('en', { timeZone, year: 'numeric' }).format(d)
  const now = new Date()
  const options: Intl.DateTimeFormatOptions =
    dayKey(date) === dayKey(now)
      ? { timeStyle: 'short' }
      : yearOf(date) === yearOf(now)
        ? { day: 'numeric', month: 'short' }
        : { dateStyle: 'medium' }
  return new Intl.DateTimeFormat(undefined, { ...options, timeZone }).format(date)
}

export function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
