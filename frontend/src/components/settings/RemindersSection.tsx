import { useState } from 'react'

import { useUpdateSettings } from '@/api/account'
import type { Preferences } from '@/api/types'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'
import { Toggle } from '@/components/ui/toggle'

import { SaveBar } from './SaveBar'

type Reminders = Preferences['reminders']

const DATE_RULES: { flag: keyof Reminders; days: keyof Reminders; label: string }[] = [
  { flag: 'deadlines', days: 'deadline_days_before', label: 'Deadlines and payments' },
  { flag: 'exams', days: 'exam_days_before', label: 'Exams' },
  { flag: 'interviews', days: 'interview_days_before', label: 'Interviews' },
  { flag: 'renewals', days: 'renewal_days_before', label: 'Certification renewals' },
]

export function RemindersSection({ preferences }: { preferences: Preferences }) {
  const [rules, setRules] = useState(preferences.reminders)
  const update = useUpdateSettings()
  const set = (key: keyof Reminders, value: boolean | number) => setRules((current) => ({ ...current, [key]: value }))

  return (
    <Card className="space-y-4">
      <CardHeader
        title="Reminders"
        description="Specify only creates the reminders you allow here. Dates are taken only when the email states them clearly; unclear ones are flagged for you to check."
      />
      {DATE_RULES.map((rule) => (
        <div key={rule.flag} className="grid items-end gap-3 sm:grid-cols-[1fr_12rem]">
          <Toggle checked={rules[rule.flag] as boolean} onChange={(value) => set(rule.flag, value)} label={rule.label} />
          <Field label="Days before">
            <input
              type="number"
              min={0}
              max={365}
              className={fieldClass}
              value={rules[rule.days] as number}
              disabled={!rules[rule.flag]}
              onChange={(e) => set(rule.days, Number(e.target.value))}
            />
          </Field>
        </div>
      ))}
      <Toggle checked={rules.reply_needed} onChange={(value) => set('reply_needed', value)} label="Remind me to reply when a sender is waiting" />
      <Field label="Follow up with recruiters after (days, 0 = off)" hint="After you ask a recruiter something; closes on its own when they reply.">
        <input type="number" min={0} max={60} className={fieldClass} value={rules.recruiter_follow_up_days} onChange={(e) => set('recruiter_follow_up_days', Number(e.target.value))} />
      </Field>
      <p className="text-xs text-muted">Reminders appear as notifications in Specify. Specify never sends email notifications or creates calendar events.</p>
      <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { reminders: rules } })} />
    </Card>
  )
}
