import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useDeleteAccount, useExportAccount, useUpdateSettings } from '@/api/account'
import type { User } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'

import { SaveBar } from './SaveBar'

export function PrivacySection({ user }: { user: User }) {
  return (
    <div className="space-y-4">
      <RetentionCard days={user.preferences.privacy.email_body_retention_days} />
      <AccessCard />
      <ExportCard />
      <DeleteAccountCard email={user.email} />
    </div>
  )
}

function RetentionCard({ days: saved }: { days: number }) {
  const [days, setDays] = useState(saved)
  const update = useUpdateSettings()
  return (
    <Card className="space-y-4">
      <CardHeader
        title="Data retention"
        description="After this many days, Specify removes the text of an email from its database. The subject, sender, folder, label and any records built from it stay, and the full email is always still in Gmail."
      />
      <Field label="Keep email text for (days, 0 = keep forever)">
        <input type="number" min={0} max={3650} className={fieldClass} value={days} onChange={(e) => setDays(Number(e.target.value))} />
      </Field>
      <p className="text-xs text-muted">Read notifications are cleared after 90 days. Removal runs once a day.</p>
      <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { privacy: { email_body_retention_days: days } } })} />
    </Card>
  )
}

function AccessCard() {
  return (
    <Card className="space-y-3">
      <CardHeader title="What Specify can do" />
      <ul className="list-disc space-y-1.5 pl-5 text-sm">
        <li>Read your email, apply labels, and save reply drafts in Gmail. It never sends, archives or deletes email.</li>
        <li>Write to the one spreadsheet you choose in Google Sheets.</li>
        <li>Keep your Google access tokens encrypted on the server. Your browser never sees them.</li>
        <li>Send email text only to the AI provider set up on this server. With Ollama, that text stays on this machine.</li>
      </ul>
      <p className="text-sm text-muted">
        Disconnect Google services on the{' '}
        <Link to="/settings?tab=accounts" className="text-primary hover:underline">
          Accounts
        </Link>{' '}
        tab, or stop all automation at once on the{' '}
        <Link to="/settings?tab=automation" className="text-primary hover:underline">
          Automation
        </Link>{' '}
        tab.
      </p>
    </Card>
  )
}

function ExportCard() {
  const download = useExportAccount()
  return (
    <Card className="space-y-3">
      <CardHeader
        title="Export your data"
        description="Download everything Specify stores about you as one JSON file: emails, labels, rules, opportunities, decisions, drafts, workflows, reminders and the activity log. Access tokens are never included."
      />
      <div className="flex items-center gap-3">
        <Button variant="outline" onClick={() => download.mutate()} disabled={download.isPending}>
          {download.isPending ? 'Preparing…' : 'Download my data'}
        </Button>
        {download.isError && <span className="text-sm text-danger">{download.error.message}</span>}
      </div>
    </Card>
  )
}

function DeleteAccountCard({ email }: { email: string }) {
  const [typed, setTyped] = useState('')
  const remove = useDeleteAccount()
  const confirmed = typed.trim().toLowerCase() === email.toLowerCase()
  return (
    <Card className="space-y-4 border-danger/40">
      <CardHeader
        title="Delete account"
        description="Revokes Specify's access to your Google account and permanently deletes everything Specify stores about you. This cannot be undone. Labels and drafts in Gmail, and your spreadsheet, stay in your Google account."
      />
      <Field label={`Type ${email} to confirm`}>
        <input className={fieldClass} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
      </Field>
      <div className="flex items-center gap-3">
        <Button variant="danger" onClick={() => remove.mutate(typed)} disabled={!confirmed || remove.isPending}>
          {remove.isPending ? 'Deleting…' : 'Delete my account'}
        </Button>
        {remove.isError && <span className="text-sm text-danger">{remove.error.message}</span>}
      </div>
    </Card>
  )
}
