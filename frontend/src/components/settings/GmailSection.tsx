import { useState } from 'react'

import { useUpdateSettings } from '@/api/account'
import type { Preferences } from '@/api/types'
import { SyncControl } from '@/components/SyncControl'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'

import { SaveBar } from './SaveBar'

export function GmailSection({ preferences }: { preferences: Preferences }) {
  const [sync, setSync] = useState(preferences.sync)
  const update = useUpdateSettings()
  const setNumber = (key: keyof Preferences['sync']) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setSync((current) => ({ ...current, [key]: Number(event.target.value) }))

  return (
    <Card>
      <CardHeader
        title="Gmail synchronization"
        description="Specify checks Gmail on a schedule and only fetches changes since the last check."
        action={<SyncControl />}
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Check every (minutes)">
          <input type="number" min={1} max={1440} className={fieldClass} value={sync.poll_interval_minutes} onChange={setNumber('poll_interval_minutes')} />
        </Field>
        <Field label="First sync: days back" hint="Used for the first sync and any full resync.">
          <input type="number" min={1} max={365} className={fieldClass} value={sync.initial_sync_days} onChange={setNumber('initial_sync_days')} />
        </Field>
        <Field label="First sync: max emails">
          <input type="number" min={10} max={5000} className={fieldClass} value={sync.initial_sync_max_messages} onChange={setNumber('initial_sync_max_messages')} />
        </Field>
      </div>
      <div className="mt-4">
        <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { sync } })} />
      </div>
    </Card>
  )
}
