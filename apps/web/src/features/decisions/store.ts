import { useSyncExternalStore } from 'react'
import { openQuestions, type Decision } from '@/mocks/data'

// In-memory store so a question answered in one screen is answered everywhere (mock of the decisions API).
let state: Decision[] = openQuestions
const listeners = new Set<() => void>()

export function setDecisions(next: Decision[]) {
  state = next
  listeners.forEach((l) => l())
}

export function useDecisions(projectId?: string) {
  const all = useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => state,
    () => state,
  )
  return projectId ? all.filter((d) => d.projectId === projectId) : all
}

// Replaces the given subset while keeping the rest of the store.
export function updateDecisions(subset: Decision[]) {
  setDecisions(state.map((d) => subset.find((s) => s.id === d.id) ?? d))
}
