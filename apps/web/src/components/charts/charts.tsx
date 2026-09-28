import { useEffect, useRef, useState } from 'react'

// Measures the container so the chart draws in real pixels (text never scales with the width).
function useWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.round(entry.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

// Lightweight SVG charts following the data-viz rules: one series in slot 1, thin marks,
// recessive grid, hover tooltip, text in text tokens (never the series color).

export function LineChart({
  data,
  format,
  label,
  height = 200,
}: {
  data: { x: string; y: number }[]
  format: (v: number) => string
  label: string
  height?: number
}) {
  const [hover, setHover] = useState<number | null>(null)
  const [ref, width] = useWidth<HTMLDivElement>()
  const pad = { top: 16, right: 16, bottom: 28, left: 56 }
  const innerW = width - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom
  const max = Math.max(...data.map((d) => d.y)) * 1.1 || 1
  const ticks = [0, max / 2, max]
  const px = (i: number) => pad.left + (data.length === 1 ? innerW / 2 : (i / (data.length - 1)) * innerW)
  const py = (v: number) => pad.top + innerH - (v / max) * innerH
  const path = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${px(i)},${py(d.y)}`).join(' ')

  return (
    <div className="relative" ref={ref}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block" role="img" aria-label={label}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={width - pad.right} y1={py(tick)} y2={py(tick)} stroke="var(--grid)" strokeWidth={1} />
            <text x={pad.left - 8} y={py(tick)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill="var(--text-muted)" className="tabular">
              {format(tick)}
            </text>
          </g>
        ))}
        {data.map((d, i) => (
          <text key={d.x} x={px(i)} y={height - 8} textAnchor="middle" fontSize={11} fill="var(--text-muted)">
            {d.x}
          </text>
        ))}
        <path d={path} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover !== null && (
          <line x1={px(hover)} x2={px(hover)} y1={pad.top} y2={pad.top + innerH} stroke="var(--axis)" strokeWidth={1} />
        )}
        {data.map((d, i) => (
          <g key={d.x}>
            <circle cx={px(i)} cy={py(d.y)} r={hover === i ? 5 : 4} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
            <rect
              x={px(i) - innerW / data.length / 2}
              y={pad.top}
              width={innerW / data.length}
              height={innerH}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            />
          </g>
        ))}
        {data.length > 0 && (
          <text x={px(data.length - 1)} y={py(data[data.length - 1].y) - 12} textAnchor="end" fontSize={12} fontWeight={600} fill="var(--text)">
            {format(data[data.length - 1].y)}
          </text>
        )}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs shadow-md"
          style={{ left: `${(px(hover) / width) * 100}%`, top: 0, transform: 'translateX(-50%)' }}
        >
          <div className="text-muted">{data[hover].x}</div>
          <div className="font-semibold text-text tabular">{format(data[hover].y)}</div>
        </div>
      )}
    </div>
  )
}

export function BarList({
  data,
  format,
}: {
  data: { label: string; value: number; hint?: string }[]
  format: (v: number) => string
}) {
  const max = Math.max(...data.map((d) => d.value)) || 1
  return (
    <ul className="space-y-3">
      {data.map((d) => (
        <li key={d.label} className="group" title={`${d.label}: ${format(d.value)}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate text-text">{d.label}</span>
            <span className="shrink-0 font-medium text-text tabular">{format(d.value)}</span>
          </div>
          <div className="h-2 w-full rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-series-1 transition-opacity group-hover:opacity-80" style={{ width: `${(d.value / max) * 100}%` }} />
          </div>
          {d.hint && <div className="mt-0.5 text-xs text-muted">{d.hint}</div>}
        </li>
      ))}
    </ul>
  )
}
