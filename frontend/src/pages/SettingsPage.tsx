import { useSearchParams } from 'react-router-dom'

import { useIntegrations } from '@/api/account'
import type { User } from '@/api/types'
import { IntegrationCard } from '@/components/IntegrationCard'
import { PreferencesForm } from '@/components/PreferencesForm'
import { AutomationSection } from '@/components/settings/AutomationSection'
import { CertificationsSection } from '@/components/settings/CertificationsSection'
import { ClassificationSection } from '@/components/settings/ClassificationSection'
import { DraftingSection } from '@/components/settings/DraftingSection'
import { GmailSection } from '@/components/settings/GmailSection'
import { LabelsSection } from '@/components/settings/LabelsSection'
import { PrivacySection } from '@/components/settings/PrivacySection'
import { RecruitmentSection } from '@/components/settings/RecruitmentSection'
import { RemindersSection } from '@/components/settings/RemindersSection'
import { RulesSection } from '@/components/settings/RulesSection'
import { SheetsSection } from '@/components/settings/SheetsSection'
import { UniversitySection } from '@/components/settings/UniversitySection'
import { Card, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/utils'

const TABS = [
  { key: 'accounts', label: 'Accounts' },
  { key: 'gmail', label: 'Gmail' },
  { key: 'sheets', label: 'Google Sheets' },
  { key: 'labeling', label: 'Labeling' },
  { key: 'labels', label: 'Labels' },
  { key: 'rules', label: 'Rules' },
  { key: 'recruitment', label: 'Recruitment' },
  { key: 'drafting', label: 'Drafting' },
  { key: 'automation', label: 'Automation' },
  { key: 'reminders', label: 'Reminders' },
  { key: 'university', label: 'University' },
  { key: 'certifications', label: 'Certifications' },
  { key: 'privacy', label: 'Privacy & security' },
  { key: 'general', label: 'General' },
] as const

type TabKey = (typeof TABS)[number]['key']

const NOTICES: Record<string, string> = {
  account_mismatch: 'Please connect the same Google account you signed in with.',
}

export function SettingsPage({ user }: { user: User }) {
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t.key === params.get('tab'))?.key ?? 'accounts') as TabKey
  const error = params.get('error')
  const connected = params.get('connected')

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold">Settings</h1>

      {error && (
        <p role="alert" className="rounded-md bg-danger/10 px-4 py-3 text-sm text-danger">
          {NOTICES[error] ?? 'The connection could not be completed. Please try again.'}
        </p>
      )}
      {connected && (
        <p role="status" className="rounded-md bg-success/10 px-4 py-3 text-sm text-success">
          {connected === 'gmail' ? 'Gmail connected. The first sync has started.' : 'Google Sheets connected. Choose a spreadsheet on the Google Sheets tab.'}
        </p>
      )}

      <nav aria-label="Settings sections" className="-mx-4 overflow-x-auto px-4">
        <ul className="flex gap-1 border-b border-border">
          {TABS.map((t) => (
            <li key={t.key}>
              <button
                onClick={() => setParams({ tab: t.key })}
                aria-current={t.key === tab ? 'page' : undefined}
                className={cn(
                  '-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap',
                  t.key === tab ? 'border-primary font-medium text-primary' : 'border-transparent text-muted hover:text-foreground',
                )}
              >
                {t.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {tab === 'accounts' && <AccountsSection />}
      {tab === 'gmail' && <GmailSection preferences={user.preferences} />}
      {tab === 'sheets' && <SheetsSection />}
      {tab === 'labeling' && <ClassificationSection preferences={user.preferences} />}
      {tab === 'labels' && <LabelsSection />}
      {tab === 'rules' && <RulesSection />}
      {tab === 'recruitment' && <RecruitmentSection preferences={user.preferences} />}
      {tab === 'drafting' && <DraftingSection preferences={user.preferences} />}
      {tab === 'automation' && <AutomationSection preferences={user.preferences} />}
      {tab === 'reminders' && <RemindersSection preferences={user.preferences} />}
      {tab === 'university' && <UniversitySection preferences={user.preferences} />}
      {tab === 'certifications' && <CertificationsSection preferences={user.preferences} />}
      {tab === 'privacy' && <PrivacySection user={user} />}
      {tab === 'general' && (
        <Card>
          <CardHeader title="General" description="Times are stored in UTC and shown in this timezone." />
          <PreferencesForm initial={user.preferences} submitLabel="Save preferences" />
        </Card>
      )}
    </div>
  )
}

function AccountsSection() {
  const { data: integrations, isLoading } = useIntegrations()
  if (isLoading) return <p className="text-sm text-muted">Loading connections…</p>
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {integrations?.map((integration) => (
        <IntegrationCard key={integration.provider} integration={integration} />
      ))}
    </div>
  )
}
