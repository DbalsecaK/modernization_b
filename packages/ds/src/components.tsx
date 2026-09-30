/**
 * NexTI base components (spec 7.4): forms, tables, alerts, tabs, modal and the function-key bar of a migrated
 * terminal screen. The only components a generated prototype may use (ADR-0013), so they are small, accessible
 * (labels tied to inputs, alerts announced) and free of any network or storage access.
 */
import {
  useEffect,
  useId,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'

function cx(...names: (string | false | undefined)[]): string {
  return names.filter(Boolean).join(' ')
}

export function Screen({
  title,
  code,
  children,
  keys,
}: {
  title: string
  code?: string
  children: ReactNode
  keys?: ReactNode
}) {
  return (
    <div className="nx-root nx-screen">
      <header className="nx-screen__header">
        <h1 className="nx-screen__title">{title}</h1>
        {code && <span className="nx-screen__code">{code}</span>}
      </header>
      <main className="nx-screen__body" aria-label={title}>
        {children}
      </main>
      {keys}
    </div>
  )
}

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="nx-card" aria-label={title}>
      {title && (
        <div className="nx-card__header nx-row">
          <h2 className="nx-card__title">{title}</h2>
          {actions && <div style={{ marginLeft: 'auto' }}>{actions}</div>}
        </div>
      )}
      <div className="nx-card__body">{children}</div>
    </section>
  )
}

export function Grid({ columns = 2, children }: { columns?: number; children: ReactNode }) {
  return (
    <div className="nx-grid" style={{ ['--nx-columns' as string]: columns }}>
      {children}
    </div>
  )
}

export function Stack({ children }: { children: ReactNode }) {
  return <div className="nx-stack">{children}</div>
}

export function Row({ children }: { children: ReactNode }) {
  return <div className="nx-row">{children}</div>
}

type FieldProps = {
  label: string
  required?: boolean
  hint?: string
  error?: string
  children: (props: { id: string; describedBy?: string; invalid: boolean }) => ReactNode
}

/** A labelled field: the child receives the id and description to wire into its input. */
export function Field({ label, required, hint, error, children }: FieldProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  return (
    <div className="nx-field">
      <label className="nx-field__label" htmlFor={id}>
        {label}
        {required && (
          <span className="nx-field__required" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {children({ id, describedBy, invalid: !!error })}
      {hint && (
        <span className="nx-field__hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="nx-field__error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  )
}

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> & {
  label: string
  hint?: string
  error?: string
  numeric?: boolean
}

export function TextField({ label, hint, error, numeric, required, className, ...input }: TextFieldProps) {
  return (
    <Field label={label} required={required} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <input
          {...input}
          id={id}
          required={required}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          inputMode={numeric ? 'numeric' : input.inputMode}
          className={cx('nx-input', numeric && 'nx-input--numeric', className)}
        />
      )}
    </Field>
  )
}

type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> & {
  label: string
  options: { value: string; label: string }[]
  hint?: string
  error?: string
}

export function SelectField({ label, options, hint, error, required, ...select }: SelectFieldProps) {
  return (
    <Field label={label} required={required} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <select
          {...select}
          id={id}
          required={required}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          className="nx-select"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}

export function Checkbox({ label, ...input }: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: string }) {
  return (
    <label className="nx-checkbox">
      <input type="checkbox" {...input} />
      {label}
    </label>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  shortcut?: string
}

export function Button({
  variant = 'secondary',
  shortcut,
  children,
  className,
  type = 'button',
  ...button
}: ButtonProps) {
  return (
    <button {...button} type={type} className={cx('nx-button', `nx-button--${variant}`, className)}>
      {children}
      {shortcut && <span className="nx-button__key">{shortcut}</span>}
    </button>
  )
}

export function Alert({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'success' | 'warning' | 'error'
  children: ReactNode
}) {
  return (
    <div className={cx('nx-alert', `nx-alert--${tone}`)} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

export function Badge({ children }: { children: ReactNode }) {
  return <span className="nx-badge">{children}</span>
}

export type Column<T> = { key: keyof T & string; label: string; numeric?: boolean }

export function DataTable<T extends Record<string, ReactNode>>({
  caption,
  columns,
  rows,
  empty = 'No data',
}: {
  caption: string
  columns: Column<T>[]
  rows: T[]
  empty?: string
}) {
  if (rows.length === 0) return <EmptyState>{empty}</EmptyState>
  return (
    <table className="nx-table">
      <caption style={{ textAlign: 'left', fontWeight: 700, paddingBottom: 8 }}>{caption}</caption>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} scope="col">
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((c) => (
              <td key={c.key} className={c.numeric ? 'nx-table__numeric' : undefined}>
                {row[c.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function Tabs({ tabs }: { tabs: { id: string; label: string; content: ReactNode }[] }) {
  const [active, setActive] = useState(tabs[0]?.id)
  const current = tabs.find((t) => t.id === active) ?? tabs[0]
  return (
    <div>
      <div className="nx-tabs__list" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={t.id === current?.id}
            className="nx-tabs__tab"
            onClick={() => setActive(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" style={{ paddingTop: 16 }}>
        {current?.content}
      </div>
    </div>
  )
}

export function Modal({
  title,
  open,
  onClose,
  children,
}: {
  title: string
  open: boolean
  onClose: () => void
  children: ReactNode
}) {
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const close = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="nx-modal__backdrop" onClick={onClose}>
      <div
        className="nx-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id={titleId} className="nx-card__title">
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}

/** The function keys of a migrated terminal screen (ENTER, PF3...), as buttons with their shortcut. */
export function KeyBar({
  actions,
}: {
  actions: { key: string; label: string; onPress?: () => void; primary?: boolean }[]
}) {
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      const name = event.key === 'Enter' ? 'ENTER' : /^F\d{1,2}$/.test(event.key) ? `PF${event.key.slice(1)}` : ''
      const action = actions.find((a) => a.key === name)
      if (action?.onPress) {
        event.preventDefault()
        action.onPress()
      }
    }
    window.addEventListener('keydown', press)
    return () => window.removeEventListener('keydown', press)
  }, [actions])
  return (
    <nav className="nx-keybar" aria-label="Actions">
      {actions.map((a) => (
        <Button key={a.key} variant={a.primary ? 'primary' : 'secondary'} shortcut={a.key} onClick={a.onPress}>
          {a.label}
        </Button>
      ))}
    </nav>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="nx-empty">{children}</div>
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return <div className="nx-spinner" role="status" aria-label={label} />
}
