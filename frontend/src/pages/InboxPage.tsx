import { SyncControl } from '@/components/SyncControl'
import { EmailBrowser } from '@/components/email/EmailBrowser'

export function InboxPage() {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Inbox</h1>
          <p className="mt-1 text-sm text-muted">Every synchronized email with how Specify classified it.</p>
        </div>
        <SyncControl />
      </div>
      <EmailBrowser />
    </div>
  )
}
