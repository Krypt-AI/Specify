import { LogOut, Menu, Moon, Search, Sun, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useLogout } from '@/api/account'
import { useEmailStats } from '@/api/emails'
import { useOpportunityStats } from '@/api/recruitment'
import { useDashboardSummary } from '@/api/reminders'
import type { User } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { NAV_SECTIONS } from './navigation'
import { NotificationsBell } from './NotificationsBell'
import { useTheme } from './theme'

export function AppLayout({ user }: { user: User }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const { theme, toggle } = useTheme()
  const logout = useLogout()
  const { data: stats } = useEmailStats()
  const { data: recruitment } = useOpportunityStats()
  const { data: summary } = useDashboardSummary()
  const badges: Record<string, number> = {
    '/inbox': stats?.needs_review ?? 0,
    '/decisions': recruitment?.decision_queue ?? 0,
    '/follow-ups': summary?.follow_ups_due ?? 0,
    '/drafts': summary?.drafts_ready ?? 0,
    '/activity': summary?.workflows_failed ?? 0,
  }

  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-64 overflow-y-auto border-r border-border bg-surface px-3 py-4 transition-transform lg:translate-x-0',
          mobileNavOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="mb-6 flex items-center justify-between px-3">
          <span className="text-lg font-semibold">Specify</span>
          <button className="lg:hidden" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation">
            <X className="size-5" />
          </button>
        </div>
        <nav className="space-y-5">
          {NAV_SECTIONS.map((section) => (
            <div key={section.title}>
              <p className="mb-1 px-3 text-xs font-medium tracking-wide text-muted uppercase">{section.title}</p>
              {section.items.map(({ label, path, icon: Icon, phase }) => (
                <NavLink
                  key={path}
                  to={path}
                  end={path === '/'}
                  onClick={() => setMobileNavOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-3 rounded-md px-3 py-2 text-sm',
                      isActive ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-background',
                      phase && !isActive && 'text-muted',
                    )
                  }
                >
                  <Icon className="size-4" aria-hidden />
                  <span className="flex-1">{label}</span>
                  {badges[path] > 0 && (
                    <span className="rounded-full bg-warning/15 px-2 text-xs font-medium text-warning">{badges[path]}</span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setMobileNavOpen(false)} />
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-surface/90 px-4 backdrop-blur">
          <button className="lg:hidden" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation">
            <Menu className="size-5" />
          </button>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-2">
            <NotificationsBell />
            <Button variant="ghost" onClick={toggle} aria-label="Toggle colour theme" className="px-2">
              {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </Button>
            <span className="hidden text-sm text-muted sm:inline">{user.email}</span>
            <Button variant="ghost" onClick={() => logout.mutate()} aria-label="Sign out" className="px-2">
              <LogOut className="size-4" />
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** Searches all emails; companies and opportunities join once they exist (Phase 3). */
function GlobalSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const q = query.trim()
    navigate(q ? `/inbox?q=${encodeURIComponent(q)}` : '/inbox')
  }

  return (
    <form onSubmit={submit} role="search" className="relative max-w-md flex-1">
      <label htmlFor="global-search" className="sr-only">
        Search emails
      </label>
      <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
      <input
        id="global-search"
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search emails"
        className="h-9 w-full rounded-md border border-border bg-background pr-3 pl-9 text-sm placeholder:text-muted"
      />
    </form>
  )
}
