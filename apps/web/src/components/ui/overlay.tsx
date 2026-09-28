import { useEffect, useRef, useSyncExternalStore, type ReactNode, type TextareaHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, X } from 'lucide-react'
import { cn } from '@/lib/cn'

// Side panel used by every create/edit form. Closes with Escape or the backdrop; focus moves into the panel.
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  wide,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  const { t } = useTranslation()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        className={cn(
          'absolute inset-y-0 right-0 flex w-full flex-col bg-surface shadow-2xl focus:outline-none',
          wide ? 'max-w-3xl' : 'max-w-xl',
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-text">{title}</h2>
            {description && <p className="mt-0.5 text-sm text-text-2">{description}</p>}
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text" aria-label={t('common.close')}>
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border px-6 py-4">{footer}</div>}
      </div>
    </div>
  )
}

// Minimal toast store for confirmations ("Saved", "Invitation sent").
type ToastItem = { id: number; message: string }
let toasts: ToastItem[] = []
const listeners = new Set<() => void>()
let nextId = 1

export function toast(message: string) {
  const id = nextId++
  toasts = [...toasts, { id, message }]
  listeners.forEach((l) => l())
  window.setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== id)
    listeners.forEach((l) => l())
  }, 3500)
}

export function Toaster() {
  const items = useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => toasts,
    () => toasts,
  )
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex flex-col gap-2" aria-live="polite">
      {items.map((item) => (
        <div key={item.id} className="flex items-center gap-2 rounded-md border border-border bg-surface px-4 py-3 text-sm text-text shadow-lg">
          <CheckCircle2 size={16} className="text-good" /> {item.message}
        </div>
      ))}
    </div>
  )
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      rows={4}
      {...props}
      className={cn(
        'w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:border-series-1 focus:outline-none',
        props.className,
      )}
    />
  )
}

export function CheckboxGroup<T extends string>({
  options,
  value,
  onChange,
  columns = 2,
}: {
  options: { id: T; label: ReactNode }[]
  value: T[]
  onChange: (v: T[]) => void
  columns?: 1 | 2 | 3
}) {
  return (
    <div className={cn('grid gap-2', columns === 2 && 'sm:grid-cols-2', columns === 3 && 'sm:grid-cols-3')}>
      {options.map((o) => {
        const on = value.includes(o.id)
        return (
          <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-text hover:bg-surface-2">
            <input type="checkbox" checked={on} onChange={() => onChange(on ? value.filter((v) => v !== o.id) : [...value, o.id])} className="accent-[var(--series-1)]" />
            {o.label}
          </label>
        )
      })}
    </div>
  )
}
