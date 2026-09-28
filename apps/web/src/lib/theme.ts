import { useSyncExternalStore } from 'react'
import { readStorage, writeStorage } from './storage'

export type Theme = 'light' | 'dark'
const KEY = 'nexti.theme'
const listeners = new Set<() => void>()

function current(): Theme {
  const stored = readStorage(KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme = current()) {
  document.documentElement.dataset.theme = theme
}

export function setTheme(theme: Theme) {
  writeStorage(KEY, theme)
  applyTheme(theme)
  listeners.forEach((l) => l())
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    current,
    () => 'light',
  )
}
