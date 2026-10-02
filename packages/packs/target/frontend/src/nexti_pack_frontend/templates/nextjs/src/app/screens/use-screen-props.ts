'use client'
import { useRouter } from 'next/navigation'
import { useMemo } from 'react'
import { createApi } from '@/api/client'
import { ROUTES } from './routes'
import type { ScreenProps } from './types'

/** What a route gives its screen: the typed client (same origin, the backend or the BFF under /api) and
 * navigate(id), which opens the route of that screen. */
export function useScreenProps(): ScreenProps {
  const router = useRouter()
  return useMemo(
    () => ({
      api: createApi(),
      navigate: (screen: string) => {
        const route = ROUTES[screen]
        if (route) router.push(route)
      },
    }),
    [router],
  )
}
