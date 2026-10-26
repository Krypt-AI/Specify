import { useState } from 'react'

import { useUpdateSettings } from '@/api/account'
import type { Preferences } from '@/api/types'
import { Card, CardHeader } from '@/components/ui/card'
import { Toggle } from '@/components/ui/toggle'

import { SaveBar } from './SaveBar'

export function ClassificationSection({ preferences }: { preferences: Preferences }) {
  const [settings, setSettings] = useState(preferences.classification)
  const update = useUpdateSettings()
  const threshold = Math.round(settings.auto_apply_threshold * 100)

  return (
    <Card className="space-y-5">
      <CardHeader
        title="Automatic labeling"
        description="The AI names a Gmail label from each email's context and reuses existing labels when they fit. Uncertain emails wait in your review queue."
      />
      <label className="block text-sm font-medium">
        Label automatically when confidence is at least {threshold}%
        <input
          type="range"
          min={50}
          max={100}
          step={5}
          value={threshold}
          onChange={(e) => setSettings({ ...settings, auto_apply_threshold: Number(e.target.value) / 100 })}
          className="mt-2 block w-full accent-primary"
        />
        <span className="mt-1 block text-xs font-normal text-muted">
          Higher means fewer automatic labels and more emails to review.
        </span>
      </label>
      <Toggle
        checked={settings.apply_gmail_labels}
        onChange={(apply_gmail_labels) => setSettings({ ...settings, apply_gmail_labels })}
        label="Apply labels in Gmail"
        description="When off, Specify still classifies emails but leaves Gmail unchanged."
      />
      <Toggle
        checked={settings.apply_status_labels}
        onChange={(apply_status_labels) => setSettings({ ...settings, apply_status_labels })}
        label="Mark emails needing attention"
        description="Adds Specify/Needs Review and Specify/Suspicious in Gmail."
        disabled={!settings.apply_gmail_labels}
      />
      <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { classification: settings } })} />
    </Card>
  )
}
