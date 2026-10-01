import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The dashboard of the active tenant (spec 18.2), by profile: executive, delivery and administrator. Money needs
// cost.view and the administrator section users.manage; the API leaves them empty otherwise.
export type Dashboard = Schemas['DashboardOut']
export type DashboardProject = Schemas['DashboardProject']
export type AdminSummary = Schemas['AdminSummary']

export const useDashboard = (enabled = true) =>
  useQuery({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/dashboard')
      if (!response.ok) throw toApiError(response, error)
      return data as Dashboard
    },
    refetchInterval: 60_000,
    enabled,
  })
