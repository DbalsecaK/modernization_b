import {
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'
import * as Switch from '@radix-ui/react-switch'
import { cn } from '@/lib/cn'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: 'sm' | 'md' }) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3 text-sm' : 'h-10 px-4 text-sm',
        variant === 'primary' && 'bg-brand text-brand-contrast hover:opacity-90',
        variant === 'secondary' && 'border border-border bg-surface text-text hover:bg-surface-2',
        variant === 'ghost' && 'text-text-2 hover:bg-surface-2 hover:text-text',
        variant === 'danger' && 'bg-critical text-white hover:opacity-90',
        className,
      )}
      {...props}
    />
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-lg border border-border bg-surface', className)}>{children}</div>
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-text">{title}</h3>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('px-5 py-4', className)}>{children}</div>
}

type Tone = 'neutral' | 'info' | 'good' | 'warning' | 'critical' | 'brand' | 'accent'

export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium',
        tone === 'neutral' && 'bg-surface-2 text-text-2',
        tone === 'info' && 'bg-info/12 text-info',
        tone === 'good' && 'bg-good/12 text-good-ink',
        tone === 'warning' && 'bg-warning/18 text-warning-ink',
        tone === 'critical' && 'bg-critical/12 text-critical-ink',
        tone === 'brand' && 'bg-brand/10 text-brand dark:text-text',
        tone === 'accent' && 'bg-accent/15 text-accent-ink',
        className,
      )}
    >
      {children}
    </span>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-text">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-text-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function StatTile({ label, value, hint }: { label: ReactNode; value: ReactNode; hint?: ReactNode }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-text">{value}</div>
      {hint && <div className="mt-1 text-xs text-text-2">{hint}</div>}
    </Card>
  )
}

export function Progress({ value, tone = 'brand' }: { value: number; tone?: 'brand' | 'warning' | 'critical' }) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn(
          'h-full rounded-full',
          tone === 'brand' && 'bg-series-1',
          tone === 'warning' && 'bg-warning',
          tone === 'critical' && 'bg-critical',
        )}
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}

// WAI-ARIA tabs: one tab stop, arrows/Home/End move between tabs. The panels are rendered by the caller, so
// Radix Tabs (which needs the panels inside its root for aria-controls) is not used here.
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode; count?: number }[]
  value: T
  onChange: (id: T) => void
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const move = (index: number) => {
    const next = (index + tabs.length) % tabs.length
    refs.current[next]?.focus()
    onChange(tabs[next].id)
  }
  return (
    <div className="mb-5 overflow-x-auto border-b border-border">
      <div className="flex min-w-max gap-1" role="tablist">
        {tabs.map((tab, i) => (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[i] = el
            }}
            role="tab"
            type="button"
            aria-selected={tab.id === value}
            tabIndex={tab.id === value ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => {
              const keys: Record<string, number> = {
                ArrowRight: i + 1,
                ArrowLeft: i - 1,
                Home: 0,
                End: tabs.length - 1,
              }
              if (e.key in keys) {
                e.preventDefault()
                move(keys[e.key])
              }
            }}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors',
              tab.id === value
                ? 'border-brand text-text dark:border-accent'
                : 'border-transparent text-muted hover:text-text',
            )}
          >
            {tab.label}
            {tab.count !== undefined && <span className="ml-1.5 text-xs text-muted">{tab.count}</span>}
          </button>
        ))}
      </div>
    </div>
  )
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  )
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        'border-b border-border px-4 py-2.5 text-xs font-medium tracking-wide text-muted uppercase',
        className,
      )}
    >
      {children}
    </th>
  )
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cn('border-b border-border px-4 py-3 align-top text-text-2', className)}>{children}</td>
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-text">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  )
}

const inputClass =
  'h-10 w-full rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-muted focus:border-series-1 focus:outline-none'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(inputClass, props.className)} />
}

export function Select({ children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={cn(inputClass, props.className)}>
      {children}
    </select>
  )
}

// On Radix Switch (D-14): role="switch", Space/Enter toggle, label associated for screen readers.
export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: ReactNode
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className={cn('flex w-fit items-center gap-3 text-sm text-text', disabled && 'opacity-60')}>
      <Switch.Root
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        className={cn(
          'relative h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-series-1' : 'bg-border',
        )}
      >
        <Switch.Thumb
          className={cn(
            'absolute top-0.5 block h-4 w-4 rounded-full bg-white shadow transition-all',
            checked ? 'left-4.5' : 'left-0.5',
          )}
        />
      </Switch.Root>
      <label htmlFor={id}>{label}</label>
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <p className="font-medium text-text">{title}</p>
      {description && <p className="mt-1 max-w-md text-sm text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Avatar({ initials }: { initials: string }) {
  return (
    <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-accent text-xs font-semibold text-[#052158]">
      {initials}
    </span>
  )
}

export function Code({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <pre
      className={cn(
        'overflow-x-auto rounded-md bg-surface-2 p-3 font-mono text-xs leading-relaxed text-text',
        className,
      )}
    >
      {children}
    </pre>
  )
}
