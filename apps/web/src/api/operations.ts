import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Platform operations (spec 18.4, NexTI only): workers and their heartbeat, queue depth, runs in progress across
// tenants and the jobs that failed in the last day.
export type PlatformStatus = Schemas['PlatformStatus']

export const usePlatformStatus = () =>
  useQuery({
    queryKey: ['platform', 'status'],
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/platform/status')
      if (!response.ok) throw toApiError(response, error)
      return data as PlatformStatus
    },
    refetchInterval: 15_000,
  })
