import { Bell } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useTimezone } from '@/api/account'
import { useMarkNotifications, useNotifications } from '@/api/reminders'
import { Button } from '@/components/ui/button'
import { cn, formatShortDate } from '@/lib/utils'

export function NotificationsBell() {
  const { data } = useNotifications()
  const mark = useMarkNotifications()
  const navigate = useNavigate()
  const timezone = useTimezone()
  const [open, setOpen] = useState(false)
  const panel = useRef<HTMLDivElement>(null)
  const unread = data?.unread ?? 0

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => !panel.current?.contains(event.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  return (
    <div className="relative" ref={panel}>
      <Button variant="ghost" className="relative px-2" onClick={() => setOpen(!open)} aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`} aria-expanded={open}>
        <Bell className="size-4" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-danger px-1 text-[10px] leading-4 font-medium text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </Button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-surface shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <span className="text-sm font-medium">Notifications</span>
            {unread > 0 && (
              <button className="text-xs text-primary hover:underline" onClick={() => mark.mutate('all')}>
                Mark all read
              </button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {(data?.items ?? []).length === 0 && <li className="px-4 py-6 text-center text-sm text-muted">You're all caught up.</li>}
            {data?.items.map((item) => (
              <li key={item.id}>
                <button
                  className={cn('block w-full px-4 py-3 text-left hover:bg-background', !item.read_at && 'bg-primary/5')}
                  onClick={() => {
                    if (!item.read_at) mark.mutate(item.id)
                    if (item.link) navigate(item.link)
                    setOpen(false)
                  }}
                >
                  <span className="flex items-baseline gap-2">
                    <span className={cn('min-w-0 flex-1 text-sm', !item.read_at && 'font-medium')}>{item.title}</span>
                    <span className="shrink-0 text-xs text-muted">{formatShortDate(item.created_at, timezone)}</span>
                  </span>
                  {item.body && <span className="mt-0.5 line-clamp-2 block text-xs text-muted">{item.body}</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
