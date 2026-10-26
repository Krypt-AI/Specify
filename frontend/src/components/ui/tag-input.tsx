import { X } from 'lucide-react'
import { useId, useState, type KeyboardEvent } from 'react'

/** Edits a list of short strings such as domains, addresses or keywords. */
export function TagInput({
  label,
  values,
  onChange,
  placeholder,
}: {
  label: string
  values: string[]
  onChange: (values: string[]) => void
  placeholder?: string
}) {
  const [draft, setDraft] = useState('')
  const id = useId()

  const commit = () => {
    const entries = draft
      .split(',')
      .map((entry) => entry.trim().toLowerCase())
      .filter((entry) => entry && !values.includes(entry))
    if (entries.length) onChange([...values, ...entries])
    setDraft('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      commit()
    } else if (event.key === 'Backspace' && !draft && values.length) {
      onChange(values.slice(0, -1))
    }
  }

  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="mt-1 flex flex-wrap gap-1.5 rounded-md border border-border bg-background p-1.5 focus-within:outline-2 focus-within:outline-primary">
        {values.map((value) => (
          <span key={value} className="inline-flex items-center gap-1 rounded bg-border/60 px-2 py-0.5 text-xs">
            {value}
            <button type="button" onClick={() => onChange(values.filter((v) => v !== value))} aria-label={`Remove ${value}`}>
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
          placeholder={values.length ? '' : placeholder}
          className="min-w-32 flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-muted"
        />
      </div>
    </div>
  )
}
