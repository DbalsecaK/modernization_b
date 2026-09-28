import { QueryClient } from '@tanstack/react-query'

// One client for the whole app: the router's guards and the components share the same cache.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
  },
})
