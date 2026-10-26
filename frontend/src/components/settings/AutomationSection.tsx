import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useUpdateSettings } from '@/api/account'
import type { Preferences } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Toggle } from '@/components/ui/toggle'
import { cn } from '@/lib/utils'

import { SaveBar } from './SaveBar'

export function AutomationSection({ preferences }: { preferences: Preferences }) {
  const [automation, setAutomation] = useState(preferences.automation)
  const update = useUpdateSettings()
  const set = (key: keyof Preferences['automation']) => (value: boolean) => setAutomation((current) => ({ ...current, [key]: value }))
  const togglePause = () =>
    update.mutate({ preferences: { automation: { paused: !preferences.automation.paused } } }, {
      onSuccess: (user) => setAutomation(user.preferences.automation),
    })

  return (
    <div className="space-y-4">
      <Card className={cn('space-y-3', preferences.automation.paused && 'border-warning')}>
        <CardHeader
          title={preferences.automation.paused ? 'Automation is paused' : 'Automation is running'}
          description="The global pause stops every workflow at once: new emails are synced but wait unprocessed, and running workflows hold where they are. Nothing is lost; resuming continues from the same place."
        />
        <Button variant={preferences.automation.paused ? 'primary' : 'danger'} onClick={togglePause} disabled={update.isPending}>
          {preferences.automation.paused ? 'Resume automation' : 'Pause all automation'}
        </Button>
      </Card>
      <Card className="space-y-4">
        <CardHeader
          title="Automatic actions"
          description="What workflows may do without asking. Sending email is never automatic: Specify only writes drafts."
        />
        <Toggle checked={automation.update_records} onChange={set('update_records')} label="Create and update recruitment records" description="Companies, contacts and opportunities from recruitment emails." />
        <Toggle checked={automation.generate_drafts} onChange={set('generate_drafts')} label="Write reply drafts after decisions" />
        <Toggle
          checked={automation.approve_before_drafting}
          onChange={set('approve_before_drafting')}
          label="Ask me before writing each draft"
          description="The workflow waits for your approval in Activity."
          disabled={!automation.generate_drafts}
        />
        <Toggle checked={automation.notify_new_opportunities} onChange={set('notify_new_opportunities')} label="Notify me about new opportunities" />
        <Toggle checked={automation.notify_failures} onChange={set('notify_failures')} label="Notify me when a workflow fails" />
        <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { automation: { ...automation, paused: preferences.automation.paused } } })} />
        <p className="text-xs text-muted">
          Automatic labeling is on the Labeling tab. Edit the steps themselves in the{' '}
          <Link to="/workflows" className="text-primary hover:underline">
            workflow builder
          </Link>
          .
        </p>
      </Card>
    </div>
  )
}
