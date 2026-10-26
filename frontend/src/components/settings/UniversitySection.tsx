import { useState } from 'react'

import { useUpdateSettings } from '@/api/account'
import type { Preferences } from '@/api/types'
import { Card, CardHeader } from '@/components/ui/card'
import { TagInput } from '@/components/ui/tag-input'

import { SaveBar } from './SaveBar'

export function UniversitySection({ preferences }: { preferences: Preferences }) {
  const [university, setUniversity] = useState(preferences.university)
  const update = useUpdateSettings()
  const set = (key: keyof Preferences['university']) => (values: string[]) =>
    setUniversity((current) => ({ ...current, [key]: values }))

  return (
    <Card className="space-y-4">
      <CardHeader
        title="University email"
        description="Emails from these senders always go to the University folder. Keywords are hints for the AI."
      />
      <TagInput label="University domains" values={university.domains} onChange={set('domains')} placeholder="um.edu.my" />
      <TagInput label="Lecturer addresses" values={university.lecturer_emails} onChange={set('lecturer_emails')} placeholder="lecturer@um.edu.my" />
      <TagInput label="Department addresses" values={university.department_emails} onChange={set('department_emails')} placeholder="registrar@um.edu.my" />
      <TagInput label="Keywords" values={university.keywords} onChange={set('keywords')} placeholder="fyp, timetable" />
      <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { university } })} />
    </Card>
  )
}
