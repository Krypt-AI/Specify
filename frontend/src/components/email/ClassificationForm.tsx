import { useState, type FormEvent } from 'react'

import { useUpdateClassification } from '@/api/emails'
import { useLabels } from '@/api/labels'
import type { EmailDetail, MailGroup } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field, fieldClass } from '@/components/ui/field'
import { Toggle } from '@/components/ui/toggle'
import { GROUP_LIST } from '@/lib/groups'

const NO_LABEL = '__none__'
const NEW_LABEL = '__new__'

/** Initial label choice: the applied label, else the AI's suggestion. */
function initialLabelChoice(email: EmailDetail) {
  if (email.label) return { choice: email.label.id, newName: '' }
  const suggestion = email.label_suggestion
  if (suggestion?.label_id) return { choice: suggestion.label_id, newName: '' }
  if (suggestion) return { choice: NEW_LABEL, newName: suggestion.name }
  return { choice: NO_LABEL, newName: '' }
}

export function ClassificationForm({ email, onDone }: { email: EmailDetail; onDone?: () => void }) {
  const { data: labels = [] } = useLabels()
  const update = useUpdateClassification(email.id)
  const initial = initialLabelChoice(email)
  const [primary, setPrimary] = useState<MailGroup>(email.primary_group ?? 'other')
  const [secondary, setSecondary] = useState<MailGroup[]>(email.secondary_groups)
  const [labelChoice, setLabelChoice] = useState(initial.choice)
  const [newLabelName, setNewLabelName] = useState(initial.newName)
  const [suspicious, setSuspicious] = useState(email.is_suspicious)

  const contextLabels = labels.filter((label) => !label.system_key && (label.enabled || label.id === labelChoice))

  const toggleSecondary = (group: MailGroup) =>
    setSecondary((current) => (current.includes(group) ? current.filter((g) => g !== group) : [...current, group]))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    update.mutate(
      {
        primary_group: primary,
        secondary_groups: secondary.filter((group) => group !== primary),
        label_id: labelChoice !== NO_LABEL && labelChoice !== NEW_LABEL ? labelChoice : null,
        new_label_name: labelChoice === NEW_LABEL ? newLabelName.trim() : null,
        ...(suspicious !== email.is_suspicious && { is_suspicious: suspicious }),
      },
      { onSuccess: onDone },
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Folder">
          <select className={fieldClass} value={primary} onChange={(e) => setPrimary(e.target.value as MailGroup)}>
            {GROUP_LIST.map((group) => (
              <option key={group.key} value={group.key}>
                {group.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Gmail label">
          <select className={fieldClass} value={labelChoice} onChange={(e) => setLabelChoice(e.target.value)}>
            <option value={NO_LABEL}>No label</option>
            {contextLabels.map((label) => (
              <option key={label.id} value={label.id}>
                {label.name}
              </option>
            ))}
            <option value={NEW_LABEL}>New label…</option>
          </select>
        </Field>
      </div>

      {labelChoice === NEW_LABEL && (
        <Field label="New label name" hint="Created in Gmail as Specify/<name>.">
          <input
            className={fieldClass}
            value={newLabelName}
            onChange={(e) => setNewLabelName(e.target.value)}
            minLength={2}
            maxLength={60}
            required
          />
        </Field>
      )}

      <fieldset>
        <legend className="text-sm font-medium">Also show in</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {GROUP_LIST.filter((group) => group.key !== primary).map((group) => (
            <label key={group.key} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={secondary.includes(group.key)}
                onChange={() => toggleSecondary(group.key)}
                className="accent-primary"
              />
              {group.label}
            </label>
          ))}
        </div>
      </fieldset>

      {email.is_suspicious && (
        <Toggle
          checked={suspicious}
          onChange={setSuspicious}
          label="Keep the Suspicious flag"
          description="Turn off only if you are sure this email is legitimate."
        />
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={update.isPending}>
          {email.processing_status === 'review_required' ? 'Confirm' : 'Save'}
        </Button>
        {onDone && (
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        )}
        {update.isError && <span className="text-sm text-danger">{update.error.message}</span>}
      </div>
    </form>
  )
}
