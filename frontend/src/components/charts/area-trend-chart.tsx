"use client"

import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent"

export type AreaTrendSeries<T> = {
  key: keyof T & string
  label: string
  /** A CSS custom property reference, e.g. "var(--chart-1)" — never a raw hex. */
  color: string
  /** "left" (area, default) or "right" (line) — a second series only makes
   * sense as a line, distinct from the primary area (plans/04 §2). */
  axis?: "left" | "right"
  valueFormatter?: (value: number) => string
}

function ChartTooltip<T>({
  active,
  payload,
  label,
  xFormatter,
  series,
}: {
  active?: boolean
  payload?: { dataKey?: string | number; value?: ValueType; name?: NameType }[]
  label?: string
  xFormatter?: (value: string) => string
  series: AreaTrendSeries<T>[]
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-border bg-popover p-3 text-sm shadow-popover">
      <p className="mb-1.5 font-medium text-foreground">{xFormatter && label ? xFormatter(label) : label}</p>
      <dl className="space-y-1">
        {payload.map((entry) => {
          const s = series.find((item) => item.key === entry.dataKey)
          if (!s || entry.value === null || entry.value === undefined) return null
          const numeric = typeof entry.value === "number" ? entry.value : Number(entry.value)
          return (
            <div key={s.key} className="flex items-center gap-2 text-caption text-muted-foreground">
              <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: s.color }} aria-hidden />
              <dt className="flex-1">{s.label}</dt>
              <dd className="font-medium text-foreground">{s.valueFormatter ? s.valueFormatter(numeric) : numeric}</dd>
            </div>
          )
        })}
      </dl>
    </div>
  )
}

// Orange line + gradient fill + dashed grid + markers (plans/00 §5). A
// second series (e.g. avg_cost_per_km) renders as a line on the right axis
// only when the caller includes it — points with a `null` value break the
// line rather than interpolating across the gap (plans/04 §2).
export function AreaTrendChart<T extends Record<string, unknown>>({
  data,
  xKey,
  xFormatter,
  series,
  height = 240,
}: {
  data: T[]
  xKey: keyof T & string
  xFormatter?: (value: string) => string
  series: AreaTrendSeries<T>[]
  height?: number
}) {
  const leftSeries = series.filter((s) => (s.axis ?? "left") === "left")
  const rightSeries = series.filter((s) => s.axis === "right")

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: rightSeries.length ? 8 : 16, left: 0, bottom: 0 }}>
          <defs>
            {series.map((s) => (
              <linearGradient id={`area-trend-${s.key}`} key={s.key} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={s.color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="4 4" stroke="var(--chart-grid)" vertical={false} />
          <XAxis
            dataKey={xKey}
            tickFormatter={xFormatter}
            stroke="var(--muted-foreground)"
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <YAxis yAxisId="left" stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} width={48} />
          {rightSeries.length > 0 && (
            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="var(--muted-foreground)"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              width={48}
            />
          )}
          <Tooltip content={<ChartTooltip xFormatter={xFormatter} series={series} />} />
          {leftSeries.map((s) => (
            <Area
              key={s.key}
              yAxisId="left"
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              fill={`url(#area-trend-${s.key})`}
              strokeWidth={2}
              dot={{ r: 3, strokeWidth: 0, fill: s.color }}
              activeDot={{ r: 4 }}
              connectNulls={false}
            />
          ))}
          {rightSeries.map((s) => (
            <Line
              key={s.key}
              yAxisId="right"
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              dot={{ r: 3, fill: s.color }}
              connectNulls={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
