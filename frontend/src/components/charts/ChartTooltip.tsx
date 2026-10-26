type Entry = { name?: string | number; value?: number | string; color?: string }

/** Tooltip in the app's surface and text tokens; the series swatch carries identity, never the text. */
export function ChartTooltip({
  active,
  payload,
  label,
  valueLabel,
}: {
  active?: boolean
  payload?: Entry[]
  label?: string | number
  valueLabel?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-foreground">{label}</p>
      {payload.map((entry) => (
        <p key={String(entry.name)} className="flex items-center gap-2 text-muted">
          <span className="size-2 rounded-full" style={{ background: entry.color }} aria-hidden />
          {payload.length > 1 ? entry.name : valueLabel}: <span className="text-foreground tabular-nums">{entry.value}</span>
        </p>
      ))}
    </div>
  )
}
