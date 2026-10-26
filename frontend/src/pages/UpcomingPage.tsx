import type { NavItem } from '@/components/layout/navigation'
import { EmptyState } from '@/components/ui/empty-state'

/** Shown for navigation entries whose feature belongs to a later roadmap phase. */
export function UpcomingPage({ item }: { item: NavItem }) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{item.label}</h1>
      <EmptyState
        icon={item.icon}
        title={`${item.label} is not available yet`}
        description={`This view is delivered in roadmap phase ${item.phase}. See docs/ROADMAP.md for what is planned.`}
      />
    </div>
  )
}
