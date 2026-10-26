import { useState } from 'react'

import { useUpdateSettings } from '@/api/account'
import { useDraftTemplates, useResetTemplate, useSaveTemplate } from '@/api/drafts'
import type { DraftTemplate, Preferences } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'
import { Toggle } from '@/components/ui/toggle'
import { cn } from '@/lib/utils'

import { SaveBar } from './SaveBar'

export function DraftingSection({ preferences }: { preferences: Preferences }) {
  const [drafting, setDrafting] = useState(preferences.drafting)
  const update = useUpdateSettings()
  const setProfile = (key: keyof Preferences['drafting']['profile']) => (event: { target: { value: string } }) =>
    setDrafting((current) => ({ ...current, profile: { ...current.profile, [key]: event.target.value } }))

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <CardHeader
          title="Drafting"
          description="Draft only: Specify writes replies and saves them in Gmail, and you send them yourself. These are the only personal details drafts may include."
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Your name">
            <input className={fieldClass} value={drafting.profile.full_name} onChange={setProfile('full_name')} maxLength={120} />
          </Field>
          <Field label="Phone (optional)">
            <input className={fieldClass} value={drafting.profile.phone} onChange={setProfile('phone')} maxLength={40} />
          </Field>
          <Field label="LinkedIn (optional)" className="sm:col-span-2">
            <input className={fieldClass} value={drafting.profile.linkedin_url} onChange={setProfile('linkedin_url')} maxLength={300} />
          </Field>
          <Field label="Signature" className="sm:col-span-2">
            <textarea
              className={cn(fieldClass, 'h-20 py-2')}
              value={drafting.profile.signature}
              onChange={setProfile('signature')}
              maxLength={500}
            />
          </Field>
          <Field label="Length">
            <select
              className={fieldClass}
              value={drafting.length}
              onChange={(e) => setDrafting({ ...drafting, length: e.target.value as typeof drafting.length })}
            >
              <option value="short">Short</option>
              <option value="medium">Medium</option>
              <option value="long">Long</option>
            </select>
          </Field>
          <Field label="Language">
            <input className={fieldClass} value={drafting.language} onChange={(e) => setDrafting({ ...drafting, language: e.target.value })} maxLength={40} />
          </Field>
        </div>
        <p className="text-xs text-muted">The default tone is on the General tab.</p>
        <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { drafting } })} />
      </Card>
      <Templates />
    </div>
  )
}

function Templates() {
  const { data: templates = [] } = useDraftTemplates()
  return (
    <Card>
      <CardHeader
        title="Templates"
        description="Guidance tells the AI what each reply should do. The wording is used when AI is off or unavailable; {placeholders} are filled in, and [brackets] are left for you."
      />
      <div className="space-y-2">
        {templates.map((template) => (
          <TemplateEditor key={`${template.scenario}-${template.customized}`} template={template} />
        ))}
      </div>
    </Card>
  )
}

function TemplateEditor({ template }: { template: DraftTemplate }) {
  const save = useSaveTemplate()
  const reset = useResetTemplate()
  const [form, setForm] = useState(template)

  return (
    <details className="rounded-md border border-border p-3">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium">
        {template.label}
        {template.customized && <Badge tone="success">Customized</Badge>}
        {!template.use_ai && <Badge>Fixed wording</Badge>}
      </summary>
      <div className="mt-3 space-y-3">
        <Toggle
          checked={form.use_ai}
          onChange={(use_ai) => setForm({ ...form, use_ai })}
          label="Let the AI write this reply"
          description="Off: always use your wording exactly."
        />
        <Field label="Guidance for the AI">
          <textarea className={cn(fieldClass, 'h-16 py-2')} value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
        </Field>
        <Field label="Wording" hint="Available: {recipient} {role} {at_company} {subject} {signature} {missing_questions} {custom_decision}">
          <textarea className={cn(fieldClass, 'h-40 py-2 font-mono text-xs')} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
        </Field>
        <div className="flex gap-2">
          <Button onClick={() => save.mutate(form)} disabled={save.isPending}>
            Save template
          </Button>
          {template.customized && (
            <Button variant="ghost" onClick={() => reset.mutate(template.scenario)}>
              Restore default
            </Button>
          )}
        </div>
        {save.isError && <p className="text-sm text-danger">{save.error.message}</p>}
      </div>
    </details>
  )
}
