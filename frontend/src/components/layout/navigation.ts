import {
  Activity,
  BarChart3,
  Bell,
  Building2,
  FileText,
  Inbox,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  Settings,
  Target,
  Workflow,
} from 'lucide-react'

import { GROUP_LIST } from '@/lib/groups'

export type NavItem = {
  label: string
  path: string
  icon: LucideIcon
  /** Roadmap phase that delivers this view; omitted once the view is live. */
  phase?: number
}

export const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: 'Overview',
    items: [{ label: 'Dashboard', path: '/', icon: LayoutDashboard }],
  },
  {
    title: 'Email',
    items: [
      { label: 'Inbox', path: '/inbox', icon: Inbox },
      ...GROUP_LIST.map(({ label, path, icon }) => ({ label, path, icon })),
    ],
  },
  {
    title: 'Recruitment',
    items: [
      { label: 'Decision Queue', path: '/decisions', icon: ListChecks },
      { label: 'Companies', path: '/companies', icon: Building2 },
      { label: 'Opportunities', path: '/opportunities', icon: Target },
      { label: 'Drafts', path: '/drafts', icon: FileText },
      { label: 'Follow-ups', path: '/follow-ups', icon: Bell },
    ],
  },
  {
    title: 'Automation',
    items: [
      { label: 'Workflow Builder', path: '/workflows', icon: Workflow },
      { label: 'Activity Logs', path: '/activity', icon: Activity },
      { label: 'Analytics', path: '/analytics', icon: BarChart3 },
      { label: 'Settings', path: '/settings', icon: Settings },
    ],
  },
]

export const UPCOMING_ITEMS = NAV_SECTIONS.flatMap((s) => s.items).filter((i) => i.phase)
