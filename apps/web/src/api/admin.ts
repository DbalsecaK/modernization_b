import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Administration data of the active tenant (spec 17). Every call is authorized by the API (OpenFGA); the
// tenant always comes from the session, never from these calls.
export type Tenant = Schemas['TenantOut']
export type Member = Schemas['MemberOut']
export type Invitation = Schemas['InvitationOut']
export type Role = Schemas['RoleOut']
export type Permission = Schemas['PermissionOut']
export type Project = Schemas['ProjectOut']
export type AuditEntry = Schemas['AuditEntryOut']
export type ChainStatus = Schemas['ChainOut']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  tenants: ['admin', 'tenants'],
  members: ['admin', 'members'],
  invitations: ['admin', 'invitations'],
  roles: ['admin', 'roles'],
  permissions: ['admin', 'permissions'],
  projects: ['admin', 'projects'],
  audit: ['admin', 'audit'],
} as const

export const useTenants = (enabled: boolean) =>
  useQuery({ queryKey: keys.tenants, queryFn: () => unwrap(api.GET('/api/v1/tenants')), enabled })
export const useMembers = (enabled = true) =>
  useQuery({ queryKey: keys.members, queryFn: () => unwrap(api.GET('/api/v1/users')), enabled })
export const useInvitations = () =>
  useQuery({ queryKey: keys.invitations, queryFn: () => unwrap(api.GET('/api/v1/invitations')) })
export const useRoles = () => useQuery({ queryKey: keys.roles, queryFn: () => unwrap(api.GET('/api/v1/roles')) })
export const usePermissions = () =>
  useQuery({ queryKey: keys.permissions, queryFn: () => unwrap(api.GET('/api/v1/permissions')) })
export const useProjects = () =>
  useQuery({ queryKey: keys.projects, queryFn: () => unwrap(api.GET('/api/v1/projects')) })

export function useAudit(before: number | null) {
  return useQuery({
    queryKey: [...keys.audit, before],
    queryFn: () => unwrap(api.GET('/api/v1/audit', { params: { query: { before: before ?? undefined, limit: 50 } } })),
  })
}

export function verifyAuditChain() {
  return unwrap(api.GET('/api/v1/audit/verify'))
}

/** A mutation that refreshes the given lists (and the audit log, where every change is recorded). */
function useAdminMutation<A, R>(fn: (args: A) => Promise<R>, refresh: readonly (readonly string[])[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all([...refresh, keys.audit].map((queryKey) => client.invalidateQueries({ queryKey })))
    },
  })
}

export const useCreateTenant = () =>
  useAdminMutation(
    (body: Schemas['TenantCreate']) => unwrap(api.POST('/api/v1/tenants', { body })),
    [keys.tenants, ['me']],
  )

export const useInvite = () =>
  useAdminMutation(
    (body: Schemas['InvitationCreate']) => unwrap(api.POST('/api/v1/invitations', { body })),
    [keys.invitations, keys.members],
  )

export const useResendInvitation = () =>
  useAdminMutation(
    (id: string) =>
      unwrap(api.POST('/api/v1/invitations/{invitation_id}:resend', { params: { path: { invitation_id: id } } })),
    [keys.invitations],
  )

export const useRevokeInvitation = () =>
  useAdminMutation(
    (id: string) =>
      unwrap(api.DELETE('/api/v1/invitations/{invitation_id}', { params: { path: { invitation_id: id } } })),
    [keys.invitations, keys.members],
  )

export const useSetMemberStatus = () =>
  useAdminMutation(
    ({ id, status }: { id: string; status: 'active' | 'suspended' }) =>
      unwrap(api.PATCH('/api/v1/users/{user_id}', { params: { path: { user_id: id } }, body: { status } })),
    [keys.members],
  )

export const useRemoveMember = () =>
  useAdminMutation(
    (id: string) => unwrap(api.DELETE('/api/v1/users/{user_id}/membership', { params: { path: { user_id: id } } })),
    [keys.members, keys.roles],
  )

export const useCreateRole = () =>
  useAdminMutation((body: Schemas['RoleCreate']) => unwrap(api.POST('/api/v1/roles', { body })), [keys.roles])

export const useDeleteRole = () =>
  useAdminMutation(
    (id: string) => unwrap(api.DELETE('/api/v1/roles/{role_id}', { params: { path: { role_id: id } } })),
    [keys.roles],
  )

export const useSetRolePermissions = () =>
  useAdminMutation(
    ({ id, permissions }: { id: string; permissions: string[] }) =>
      unwrap(
        api.PUT('/api/v1/roles/{role_id}/permissions', { params: { path: { role_id: id } }, body: { permissions } }),
      ),
    [keys.roles, ['me']],
  )

// Base roles have a translated name; roles created by the tenant show the name they were given.
const BASE_ROLES = new Set([
  'tenantAdmin',
  'auditor',
  'finance',
  'projectOwner',
  'architect',
  'analyst',
  'businessReviewer',
  'developer',
  'observer',
])

export function roleLabel(t: (key: string) => string, role: { key: string; name: string; isSystem?: boolean }) {
  return BASE_ROLES.has(role.key) ? t(`roles.${role.key}`) : role.name
}

// Integrations of the tenant (M7, ADR-0018): the token goes to the secrets store and never comes back.
export type Integration = Schemas['IntegrationOut']
export type IntegrationKind = Integration['kind']
const integrationsKey = ['admin', 'integrations'] as const

export const useIntegrations = (enabled = true) =>
  useQuery({ queryKey: integrationsKey, queryFn: () => unwrap(api.GET('/api/v1/integrations')), enabled })
export const useCreateIntegration = () =>
  useAdminMutation(
    (body: Schemas['IntegrationCreate']) => unwrap(api.POST('/api/v1/integrations', { body })),
    [integrationsKey],
  )
export const useUpdateIntegration = () =>
  useAdminMutation(
    ({ id, ...body }: Schemas['IntegrationUpdate'] & { id: string }) =>
      unwrap(api.PATCH('/api/v1/integrations/{integration_id}', { params: { path: { integration_id: id } }, body })),
    [integrationsKey],
  )
export const useDeleteIntegration = () =>
  useAdminMutation(
    (id: string) =>
      unwrap(api.DELETE('/api/v1/integrations/{integration_id}', { params: { path: { integration_id: id } } })),
    [integrationsKey],
  )
export const useTestIntegration = () =>
  useAdminMutation(
    (id: string) =>
      unwrap(api.POST('/api/v1/integrations/{integration_id}:test', { params: { path: { integration_id: id } } })),
    [integrationsKey],
  )
