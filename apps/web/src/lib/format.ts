import i18n from '@/i18n'

// Formatting follows the UI language, independent of the language of the data.
const locale = () => (i18n.language === 'es' ? 'es-EC' : 'en-US')

export function formatUsd(value: number, digits = 0) {
  return new Intl.NumberFormat(locale(), {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value)
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat(locale()).format(value)
}

export function formatCompact(value: number) {
  return new Intl.NumberFormat(locale(), { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

export function formatDate(iso: string) {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(locale(), { dateStyle: 'medium' }).format(new Date(iso))
}

export function formatDateTime(iso: string) {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
}

export function formatMonth(yyyyMm: string) {
  const [y, m] = yyyyMm.split('-').map(Number)
  return new Intl.DateTimeFormat(locale(), { month: 'short' }).format(new Date(Date.UTC(y, m - 1, 15)))
}
