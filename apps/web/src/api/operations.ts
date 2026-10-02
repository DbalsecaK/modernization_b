import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Platform operations (spec 18.4, NexTI only): workers and their heartbeat, queue depth, runs in progress across
// tenants and the jobs that failed in the last day.
// The offline license (ADR-0030), as LicenseOut in the API. Written by hand until the schema is regenerated; the
// intersection stays valid once Schemas['PlatformStatus'] includes it.
export type LicenseState = 'not_required' | 'valid' | 'missing' | 'invalid' | 'expired' | 'over_limits'
export type LicenseStatus = {
  state: LicenseState
  readOnly: boolean
  reason?: string | null
  licenseId?: string | null
  customer?: string | null
  deploymentProfile?: string | null
  issuedAt?: string | null
  expiresAt?: string | null
  maxTenants?: number | null
  maxProjects?: number | null
  features?: string[]
  tenants?: number | null
  projects?: number | null
}
export type PlatformStatus = Schemas['PlatformStatus'] & { license: LicenseStatus }

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
