import { useState } from 'react'

import { useUpdateSettings } from '@/api/account'
import type { Preferences } from '@/api/types'
import { Card, CardHeader } from '@/components/ui/card'
import { Field, fieldClass } from '@/components/ui/field'
import { TagInput } from '@/components/ui/tag-input'

import { SaveBar } from './SaveBar'

const ARRANGEMENTS = [
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'On-site' },
] as const

export function RecruitmentSection({ preferences }: { preferences: Preferences }) {
  const [recruitment, setRecruitment] = useState(preferences.recruitment)
  const update = useUpdateSettings()
  const salary = recruitment.min_salary

  const toggleArrangement = (value: (typeof ARRANGEMENTS)[number]['value']) =>
    setRecruitment((current) => ({
      ...current,
      work_arrangements: current.work_arrangements.includes(value)
        ? current.work_arrangements.filter((a) => a !== value)
        : [...current.work_arrangements, value],
    }))

  return (
    <Card className="space-y-4">
      <CardHeader
        title="Recruitment preferences"
        description="Opportunities that don't match are flagged in the decision panel. Nothing is declined automatically."
      />
      <TagInput
        label="Job types"
        values={recruitment.job_types}
        onChange={(job_types) => setRecruitment({ ...recruitment, job_types })}
        placeholder="full-time, internship"
      />
      <TagInput
        label="Locations"
        values={recruitment.locations}
        onChange={(locations) => setRecruitment({ ...recruitment, locations })}
        placeholder="kuala lumpur, singapore"
      />
      <fieldset>
        <legend className="text-sm font-medium">Work arrangement</legend>
        <div className="mt-1 flex flex-wrap gap-4">
          {ARRANGEMENTS.map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                className="accent-primary"
                checked={recruitment.work_arrangements.includes(option.value)}
                onChange={() => toggleArrangement(option.value)}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Minimum salary">
          <input
            type="number"
            min={0}
            className={fieldClass}
            value={salary.amount ?? ''}
            onChange={(e) =>
              setRecruitment({ ...recruitment, min_salary: { ...salary, amount: e.target.value === '' ? null : Number(e.target.value) } })
            }
          />
        </Field>
        <Field label="Currency">
          <input
            className={fieldClass}
            value={salary.currency ?? ''}
            maxLength={3}
            placeholder="MYR"
            onChange={(e) =>
              setRecruitment({ ...recruitment, min_salary: { ...salary, currency: e.target.value.toUpperCase() || null } })
            }
          />
        </Field>
        <Field label="Per">
          <select
            className={fieldClass}
            value={salary.period}
            onChange={(e) =>
              setRecruitment({ ...recruitment, min_salary: { ...salary, period: e.target.value as typeof salary.period } })
            }
          >
            {['year', 'month', 'week', 'day', 'hour'].map((period) => (
              <option key={period} value={period}>
                {period}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <SaveBar mutation={update} onSave={() => update.mutate({ preferences: { recruitment } })} />
    </Card>
  )
}
