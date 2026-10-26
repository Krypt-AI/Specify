import { EmailBrowser } from '@/components/email/EmailBrowser'
import type { GroupInfo } from '@/lib/groups'

/** An email folder. University and Certifications are folders only, not course or study tools. */
export function FolderPage({ group }: { group: GroupInfo }) {
  const Icon = group.icon
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <Icon className="mt-1 size-6 text-primary" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">{group.label}</h1>
          <p className="mt-1 text-sm text-muted">{group.description}</p>
        </div>
      </div>
      {/* Remount per folder so filters and selection don't leak between folders. */}
      <EmailBrowser key={group.key} folder={group.key} />
    </div>
  )
}
