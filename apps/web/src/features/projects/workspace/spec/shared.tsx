import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Link2 } from 'lucide-react'
import { cn } from '@/lib/cn'
import { ApiError } from '@/api/client'
import type { GherkinProblem } from '@/api/spec'
import { camelKey } from './model'

// Small pieces shared by the views of the specification tab (same look as the prototype).

export function errorText(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback
}

/** The server's Gherkin problems, translated by code (the API's English message is the fallback). */
export function GherkinProblems({ problems, numbered }: { problems: GherkinProblem[]; numbered?: boolean }) {
  const { t } = useTranslation()
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-critical-ink" aria-live="polite">
      {problems.map((p, i) => (
        <li key={i} className="flex items-start gap-1">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>
            {numbered && <b>{t('gherkin.scenario', { n: p.criterion + 1 })} · </b>}
            {p.line > 0 && <>{t('gherkin.line', { line: p.line })} </>}
            {t(`gherkin.api.${camelKey(p.code)}`, { defaultValue: p.message })}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function Gap({
  label,
  items,
  tone = 'warning',
}: {
  label: string
  items: string[]
  tone?: 'warning' | 'neutral'
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <AlertTriangle size={14} className={tone === 'warning' ? 'text-warning' : 'text-muted'} />
      <span className="text-text-2">{label}</span>
      {items.map((i) => (
        <span key={i} className="font-mono text-xs text-text">
          {i}
        </span>
      ))}
    </div>
  )
}

export function Links({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted">{label}</div>
      {items.length === 0 ? (
        <span className="text-xs text-muted">—</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {items.map((i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text"
            >
              <Link2 size={10} className="text-muted" /> {i}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function Meta({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="text-text">{value}</dd>
    </div>
  )
}

export function IconBtn({
  label,
  icon,
  onClick,
  disabled,
}: {
  label: string
  icon: ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="rounded border border-border p-1 text-muted hover:bg-surface-2 hover:text-text disabled:opacity-40"
    >
      {icon}
    </button>
  )
}

/** A list selector button of the master/detail views. */
export function ListButton({
  selected,
  onClick,
  children,
}: {
  selected: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      aria-current={selected}
      className={cn('w-full px-4 py-2.5 text-left hover:bg-surface-2', selected && 'bg-surface-2')}
    >
      {children}
    </button>
  )
}
