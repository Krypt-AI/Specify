import { RefreshCw } from 'lucide-react'

import { useTimezone } from '@/api/account'
import { useSyncStatus, useTriggerSync } from '@/api/sync'
import { Button } from '@/components/ui/button'
import { cn, formatDateTime } from '@/lib/utils'

export function SyncControl() {
  const { data: status } = useSyncStatus()
  const trigger = useTriggerSync()
  const timezone = useTimezone()
  if (!status?.connected) return null

  const running = status.status === 'running' || trigger.isPending
  const detail = running
    ? 'Synchronizing…'
    : status.queued_emails > 0
      ? `Classifying ${status.queued_emails} email${status.queued_emails === 1 ? '' : 's'}…`
      : `Last synced ${formatDateTime(status.last_synced_at, timezone)}`

  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className={cn('text-xs', status.status === 'error' ? 'text-danger' : 'text-muted')}>
        {status.status === 'error' && status.last_error ? status.last_error : detail}
      </span>
      <Button variant="outline" onClick={() => trigger.mutate()} disabled={running}>
        <RefreshCw className={cn('size-4', running && 'animate-spin')} aria-hidden />
        Sync now
      </Button>
      {trigger.isError && <span className="text-xs text-danger">{trigger.error.message}</span>}
    </div>
  )
}
