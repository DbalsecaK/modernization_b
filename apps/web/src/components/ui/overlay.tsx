import { useRef, useSyncExternalStore, type ReactNode, type TextareaHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import * as Dialog from '@radix-ui/react-dialog'
import * as ToastPrimitive from '@radix-ui/react-toast'
import { CheckCircle2, X } from 'lucide-react'
import { cn } from '@/lib/cn'

// Side panel used by every create/edit form, on Radix Dialog (D-14, ADR-0003): focus is trapped inside and
// returns to the opener on close; Escape and the backdrop close it; title and description are announced.
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
  // Radix returns focus to a Dialog.Trigger; these drawers are opened by any button, so the opener is kept here.
  const opener = useRef<HTMLElement | null>(null)
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className={cn(
            'fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-surface shadow-2xl focus:outline-none',
            wide ? 'max-w-3xl' : 'max-w-xl',
          )}
          {...(description ? {} : { 'aria-describedby': undefined })}
          onOpenAutoFocus={() => {
            opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            opener.current?.focus()
          }}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-lg font-semibold text-text">{title}</Dialog.Title>
              {description && (
                <Dialog.Description className="mt-0.5 text-sm text-text-2">{description}</Dialog.Description>
              )}
            </div>
            <Dialog.Close
              className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text"
              aria-label={t('common.close')}
            >
              <X size={18} />
            </Dialog.Close>
          </div>
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-border px-6 py-4">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

// Confirmations ("Saved", "Invitation sent") on Radix Toast: announced to screen readers, dismissable with
// the keyboard (F8 focuses the region, Escape closes). `toast(message)` works from anywhere.
type ToastItem = { id: number; message: string }
let toasts: ToastItem[] = []
const listeners = new Set<() => void>()
let nextId = 1

function emit() {
  listeners.forEach((l) => l())
}

export function toast(message: string) {
  toasts = [...toasts, { id: nextId++, message }]
  emit()
}

function dismiss(id: number) {
  toasts = toasts.filter((x) => x.id !== id)
  emit()
}

export function Toaster() {
  const { t } = useTranslation()
  const items = useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => toasts,
    () => toasts,
  )
  return (
    <ToastPrimitive.Provider duration={3500} label={t('topbar.notifications')}>
      {items.map((item) => (
        <ToastPrimitive.Root
          key={item.id}
          onOpenChange={(open) => !open && dismiss(item.id)}
          className="flex items-center gap-2 rounded-md border border-border bg-surface px-4 py-3 text-sm text-text shadow-lg"
        >
          <CheckCircle2 size={16} className="text-good" aria-hidden />
          <ToastPrimitive.Description>{item.message}</ToastPrimitive.Description>
        </ToastPrimitive.Root>
      ))}
      <ToastPrimitive.Viewport className="fixed bottom-4 left-4 z-[60] flex max-w-sm flex-col gap-2 outline-none" />
    </ToastPrimitive.Provider>
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
          <label
            key={o.id}
            className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-text hover:bg-surface-2"
          >
            <input
              type="checkbox"
              checked={on}
              onChange={() => onChange(on ? value.filter((v) => v !== o.id) : [...value, o.id])}
              className="accent-[var(--series-1)]"
            />
            {o.label}
          </label>
        )
      })}
    </div>
  )
}
