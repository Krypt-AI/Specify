import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useLabels } from '@/api/labels'
import { useCreateRule, useDeleteRule, useRuleSuggestions, useRules, useUpdateRule } from '@/api/rules'
import type { MailGroup, Rule, RuleConditions } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'
import { TagInput } from '@/components/ui/tag-input'
import { Toggle } from '@/components/ui/toggle'
import { GROUPS, GROUP_LIST } from '@/lib/groups'

const EMPTY_CONDITIONS: RuleConditions = { sender_emails: [], sender_domains: [], subject_contains: [], body_contains: [] }

export function RulesSection() {
  const { data: rules = [] } = useRules()
  const { data: suggestions = [] } = useRuleSuggestions()
  const create = useCreateRule()

  return (
    <div className="space-y-4">
      {suggestions.length > 0 && (
        <Card>
          <CardHeader title="Suggested rules" description="Based on corrections you made. Nothing changes until you add one." />
          <ul className="divide-y divide-border">
            {suggestions.map((suggestion) => (
              <li key={suggestion.rule.name} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{suggestion.rule.name} → {GROUPS[suggestion.rule.target_group].label}</p>
                  <p className="text-xs text-muted">{suggestion.reason}</p>
                </div>
                <Button variant="outline" onClick={() => create.mutate(suggestion.rule)} disabled={create.isPending}>
                  Add rule
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Your rules"
          description="Rules run before the AI and always decide the folder, and optionally the label. They run in the order you created them."
        />
        {rules.length === 0 ? (
          <p className="text-sm text-muted">No rules yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {rules.map((rule) => (
              <RuleRow key={rule.id} rule={rule} />
            ))}
          </ul>
        )}
      </Card>

      <NewRuleForm />
    </div>
  )
}

function describe(conditions: RuleConditions) {
  const parts = [
    conditions.sender_emails.length && `from ${conditions.sender_emails.join(', ')}`,
    conditions.sender_domains.length && `from domain ${conditions.sender_domains.join(', ')}`,
    conditions.subject_contains.length && `subject has ${conditions.subject_contains.join(' or ')}`,
    conditions.body_contains.length && `text has ${conditions.body_contains.join(' or ')}`,
  ].filter(Boolean)
  return parts.join(' and ')
}

function RuleRow({ rule }: { rule: Rule }) {
  const update = useUpdateRule()
  const remove = useDeleteRule()
  const { data: labels = [] } = useLabels()
  const label = labels.find((l) => l.id === rule.target_label_id)

  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{rule.name}</p>
        <p className="text-xs text-muted">
          {describe(rule.conditions)} → {GROUPS[rule.target_group].label}
          {label && `, label ${label.name}`}
        </p>
      </div>
      <div className="w-28">
        <Toggle
          checked={rule.enabled}
          onChange={(enabled) => update.mutate({ id: rule.id, enabled })}
          label={rule.enabled ? 'On' : 'Off'}
        />
      </div>
      <Button
        variant="ghost"
        className="px-2"
        onClick={() => window.confirm(`Delete the rule "${rule.name}"?`) && remove.mutate(rule.id)}
        aria-label={`Delete ${rule.name}`}
      >
        <Trash2 className="size-4" />
      </Button>
    </li>
  )
}

function NewRuleForm() {
  const create = useCreateRule()
  const { data: labels = [] } = useLabels()
  const [name, setName] = useState('')
  const [conditions, setConditions] = useState<RuleConditions>(EMPTY_CONDITIONS)
  const [group, setGroup] = useState<MailGroup>('recruitment')
  const [labelId, setLabelId] = useState('')
  const set = (key: keyof RuleConditions) => (values: string[]) => setConditions((c) => ({ ...c, [key]: values }))
  const hasCondition = Object.values(conditions).some((values) => values.length > 0)

  const submit = () =>
    create.mutate(
      { name: name.trim(), conditions, target_group: group, target_label_id: labelId || null },
      {
        onSuccess: () => {
          setName('')
          setConditions(EMPTY_CONDITIONS)
          setLabelId('')
        },
      },
    )

  return (
    <Card className="space-y-4">
      <CardHeader title="New rule" description="All filled-in conditions must match. Within one condition, any entry may match." />
      <Field label="Rule name">
        <input className={fieldClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <TagInput label="Sender addresses" values={conditions.sender_emails} onChange={set('sender_emails')} placeholder="hr@company.com" />
        <TagInput label="Sender domains" values={conditions.sender_domains} onChange={set('sender_domains')} placeholder="company.com" />
        <TagInput label="Subject contains" values={conditions.subject_contains} onChange={set('subject_contains')} placeholder="interview" />
        <TagInput label="Text contains" values={conditions.body_contains} onChange={set('body_contains')} placeholder="job offer" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Put in folder">
          <select className={fieldClass} value={group} onChange={(e) => setGroup(e.target.value as MailGroup)}>
            {GROUP_LIST.map((g) => (
              <option key={g.key} value={g.key}>
                {g.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Apply label (optional)">
          <select className={fieldClass} value={labelId} onChange={(e) => setLabelId(e.target.value)}>
            <option value="">Let the AI choose</option>
            {labels
              .filter((label) => !label.system_key && label.enabled)
              .map((label) => (
                <option key={label.id} value={label.id}>
                  {label.name}
                </option>
              ))}
          </select>
        </Field>
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={!name.trim() || !hasCondition || create.isPending}>
          Add rule
        </Button>
        {create.isError && <span className="text-sm text-danger">{create.error.message}</span>}
      </div>
    </Card>
  )
}
