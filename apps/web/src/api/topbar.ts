import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The top bar (spec 18.1): the global search over projects and rules the user may see, and the notifications derived
// from tasks, runs, verdicts and budget alerts. Agents and skills are searched in the catalog the web already has.
export type SearchHit = Schemas['SearchHit']
export type Notification = Schemas['NotificationOut']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

/** The value after it stopped changing for `ms` (fewer requests while the user types). */
export function useDebounced<T>(value: T, ms = 250): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

export const useSearchHits = (query: string, enabled: boolean) =>
  useQuery({
    queryKey: ['search', query],
    queryFn: () => unwrap(api.GET('/api/v1/search', { params: { query: { q: query } } })),
    enabled: enabled && query.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })

export const useNotifications = (enabled: boolean) =>
  useQuery({
    queryKey: ['notifications'],
    queryFn: () => unwrap(api.GET('/api/v1/notifications')),
    refetchInterval: 60_000,
    enabled,
  })
