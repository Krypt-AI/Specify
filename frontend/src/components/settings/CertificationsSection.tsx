import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useUpdateSettings } from '@/api/account'
import type { CertificationProvider, Preferences } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'
import { TagInput } from '@/components/ui/tag-input'

import { SaveBar } from './SaveBar'

export function CertificationsSection({ preferences }: { preferences: Preferences }) {
  const [providers, setProviders] = useState<CertificationProvider[]>(preferences.certifications.providers)
  const update = useUpdateSettings()
  const change = (index: number, provider: CertificationProvider) =>
    setProviders((current) => current.map((p, i) => (i === index ? provider : p)))

  return (
    <Card className="space-y-4">
      <CardHeader
        title="Certification providers"
        description="Help the AI recognize certification email. A provider's domain is only a hint: a marketing email from a provider is not treated as a certification email."
      />
      <ul className="space-y-3">
        {providers.map((provider, index) => (
          <li key={index} className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-[12rem_1fr_auto]">
            <Field label="Provider">
              <input
                className={fieldClass}
                value={provider.name}
                onChange={(e) => change(index, { ...provider, name: e.target.value })}
                maxLength={80}
              />
            </Field>
            <TagInput
              label="Sender domains (optional)"
              values={provider.domains}
              onChange={(domains) => change(index, { ...provider, domains })}
              placeholder="provider.org"
            />
            <Button
              variant="ghost"
              className="self-end px-2"
              onClick={() => setProviders((current) => current.filter((_, i) => i !== index))}
              aria-label={`Remove ${provider.name || 'provider'}`}
            >
              <Trash2 className="size-4" />
            </Button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={() => setProviders((current) => [...current, { name: '', domains: [] }])}>
          Add provider
        </Button>
        <SaveBar
          mutation={update}
          onSave={() =>
            update.mutate({ preferences: { certifications: { providers: providers.filter((p) => p.name.trim()) } } })
          }
        />
      </div>
    </Card>
  )
}
