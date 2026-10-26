import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useIntegrations } from '@/api/account'
import type { User } from '@/api/types'
import { IntegrationCard } from '@/components/IntegrationCard'
import { PreferencesForm } from '@/components/PreferencesForm'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

// Steps for categories, labels, recruitment rules and workflow activation join as their phases ship.
const STEPS = ['Connect Gmail', 'Connect Google Sheets', 'Preferences'] as const

export function SetupWizardPage({ user }: { user: User }) {
  // OAuth returns with ?connected=<provider>; resume on that provider's step.
  const [params] = useSearchParams()
  const [step, setStep] = useState(params.get('connected') === 'sheets' ? 1 : 0)
  const { data: integrations = [] } = useIntegrations()
  const integration = integrations.find((i) => i.provider === (step === 0 ? 'gmail' : 'sheets'))

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-10">
      <div>
        <h1 className="text-2xl font-semibold">Set up Specify</h1>
        <p className="mt-1 text-sm text-muted">Optional steps can be skipped and completed later in Settings.</p>
      </div>

      <ol className="flex gap-2">
        {STEPS.map((label, index) => (
          <li
            key={label}
            className={cn(
              'flex-1 border-t-2 pt-2 text-xs font-medium',
              index <= step ? 'border-primary text-primary' : 'border-border text-muted',
            )}
          >
            {index + 1}. {label}
          </li>
        ))}
      </ol>

      {step < 2 ? (
        <>
          {integration && <IntegrationCard integration={integration} />}
          <div className="flex justify-between">
            <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={step === 0}>
              Back
            </Button>
            <Button variant={integration?.connected ? 'primary' : 'outline'} onClick={() => setStep(step + 1)}>
              {integration?.connected ? 'Continue' : 'Skip for now'}
            </Button>
          </div>
        </>
      ) : (
        <Card>
          <PreferencesForm initial={user.preferences} submitLabel="Finish setup" completeSetup />
        </Card>
      )}
    </div>
  )
}
