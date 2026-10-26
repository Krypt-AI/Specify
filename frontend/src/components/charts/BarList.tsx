import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { ChartTooltip } from './ChartTooltip'

export type BarDatum = { label: string; value: number }

/** Magnitude across categories: one hue, horizontal bars, values direct-labeled at the bar end. */
export function BarList({ data, valueLabel }: { data: BarDatum[]; valueLabel: string }) {
  const height = Math.max(120, data.length * 32 + 24)
  return (
    <div style={{ height }} role="img" aria-label={`${valueLabel} by category`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 32, bottom: 4, left: 8 }} barCategoryGap={6}>
          <CartesianGrid horizontal={false} stroke="var(--chart-grid)" />
          <XAxis type="number" allowDecimals={false} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={{ stroke: 'var(--chart-grid)' }} tickLine={false} />
          <YAxis type="category" dataKey="label" width={150} tick={{ fill: 'var(--color-foreground)', fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip cursor={{ fill: 'var(--chart-grid)', opacity: 0.4 }} content={<ChartTooltip valueLabel={valueLabel} />} />
          <Bar
            dataKey="value"
            name={valueLabel}
            fill="var(--chart-sequential)"
            radius={[0, 4, 4, 0]}
            maxBarSize={20}
            label={{ position: 'right', fill: 'var(--color-foreground)', fontSize: 11 }}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
