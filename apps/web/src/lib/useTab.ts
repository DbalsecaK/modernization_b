import { useNavigate, useSearch } from '@tanstack/react-router'

// Tabs are kept in the URL (?tab=) so every view can be linked and shared (spec 18.5).
export function useTab<T extends string>(allowed: readonly T[], fallback: T) {
  const search = useSearch({ strict: false }) as { tab?: string }
  const navigate = useNavigate()
  const tab = (allowed as readonly string[]).includes(search.tab ?? '') ? (search.tab as T) : fallback
  const setTab = (next: T) =>
    void navigate({
      to: '.',
      search: ((prev: Record<string, unknown>) => ({ ...prev, tab: next })) as never,
      replace: true,
    })
  return [tab, setTab] as const
}
