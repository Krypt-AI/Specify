import { useState, type FormEvent } from 'react'

import { useUpdateSettings } from '@/api/account'
import type { DraftTone, Preferences } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field, fieldClass } from '@/components/ui/field'
import { BROWSER_TIMEZONE, DRAFT_TONES, TIMEZONES } from '@/lib/preferences'

export function PreferencesForm({
  initial,
  submitLabel,
  completeSetup = false,
}: {
  initial: Preferences
  submitLabel: string
  completeSetup?: boolean
}) {
  const [timezone, setTimezone] = useState(initial.timezone ?? BROWSER_TIMEZONE)
  const [draftTone, setDraftTone] = useState<DraftTone>(initial.draft_tone)
  const update = useUpdateSettings()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    update.mutate({
      preferences: { timezone, draft_tone: draftTone },
      ...(completeSetup && { setup_completed: true }),
    })
  }

  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
      <Field label="Timezone">
        <select className={fieldClass} value={timezone} onChange={(e) => setTimezone(e.target.value)}>
          {TIMEZONES.map((tz) => (
            <option key={tz}>{tz}</option>
          ))}
        </select>
      </Field>
      <Field label="Default draft tone">
        <select className={fieldClass} value={draftTone} onChange={(e) => setDraftTone(e.target.value as DraftTone)}>
          {DRAFT_TONES.map((tone) => (
            <option key={tone.value} value={tone.value}>
              {tone.label}
            </option>
          ))}
        </select>
      </Field>
      <div className="flex items-center gap-3 sm:col-span-2">
        <Button type="submit" disabled={update.isPending}>
          {submitLabel}
        </Button>
        {update.isSuccess && !completeSetup && <span className="text-sm text-success">Saved</span>}
        {update.isError && <span className="text-sm text-danger">{update.error.message}</span>}
      </div>
    </form>
  )
}
