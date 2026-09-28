import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Download, Plus, RotateCw, ShieldCheck, Trash2 } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { formatDateTime } from '@/lib/format'
import { identityProviders } from '@/mocks/data'
import { can, useMe } from '@/api/session'
import {
  roleLabel,
  useAudit,
  useDeleteRole,
  useInvitations,
  useMembers,
  usePermissions,
  useRemoveMember,
  useResendInvitation,
  useRevokeInvitation,
  useRoles,
  useSetMemberStatus,
  useSetRolePermissions,
  useTenants,
  verifyAuditChain,
  type AuditEntry,
  type ChainStatus,
  type Role,
} from '@/api/admin'
import { toast } from '@/components/ui/overlay'
import { errorMessage, IdentityProviderForm, InviteForm, RoleForm, TenantForm } from './AdminForms'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  Table,
  Tabs,
  Td,
  Th,
  Toggle,
} from '@/components/ui/primitives'
import { Notice } from '@/features/projects/NewProjectWizard'

const TABS = ['tenants', 'users', 'roles', 'authentication', 'security', 'integrations', 'audit'] as const
type Tab = (typeof TABS)[number]

export function AdminPage() {
  const { t } = useTranslation()
  const me = useMe()
  const isSuperAdmin = !!me?.platformRoles.includes('superAdmin')
  const manageUsers = can(me, 'users.manage')
  const visible = TABS.filter((tab) => {
    if (tab === 'tenants') return isSuperAdmin
    if (tab === 'audit') return can(me, 'audit.view')
    return manageUsers
  })
  const [tab, setTab] = useTab<Tab>(visible.length ? visible : ['users'], visible[0] ?? 'users')
  return (
    <>
      <PageHeader title={t('admin.title')} description={t('admin.description')} />
      <Tabs tabs={visible.map((id) => ({ id, label: t(`admin.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {!me?.activeTenant && tab !== 'tenants' && <Notice tone="info">{t('admin.noActiveTenant')}</Notice>}
      {tab === 'tenants' && <Tenants />}
      {tab === 'users' && me?.activeTenant && <Users />}
      {tab === 'roles' && me?.activeTenant && <Roles />}
      {tab === 'authentication' && <Authentication />}
      {tab === 'security' && <Security />}
      {tab === 'integrations' && <Integrations />}
      {tab === 'audit' && me?.activeTenant && <Audit />}
    </>
  )
}

function useLanguageName() {
  const { i18n } = useTranslation()
  return (code: string) => new Intl.DisplayNames([i18n.language], { type: 'language' }).of(code) ?? code
}

/** Runs a mutation with a toast on success or failure. */
async function run(action: () => Promise<unknown>, ok: string, fail: (message: string) => string) {
  try {
    await action()
    toast(ok)
  } catch (error) {
    toast(fail(errorMessage(error)))
  }
}

function Tenants() {
  const { t } = useTranslation()
  const tenants = useTenants(true)
  const languageName = useLanguageName()
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <TenantForm key={String(open)} open={open} onClose={() => setOpen(false)} />
      <CardHeader
        title={t('admin.tenantsTitle')}
        action={
          <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
            <Plus size={14} /> {t('admin.newTenant')}
          </Button>
        }
      />
      <Table>
        <thead>
          <tr>
            <Th>{t('admin.tenant')}</Th>
            <Th>{t('admin.tenantSlug')}</Th>
            <Th>{t('admin.deployment')}</Th>
            <Th>{t('admin.defaultLanguage')}</Th>
            <Th>{t('admin.status')}</Th>
          </tr>
        </thead>
        <tbody>
          {(tenants.data ?? []).map((x) => (
            <tr key={x.id}>
              <Td className="font-medium text-text">{x.name}</Td>
              <Td className="font-mono text-xs">{x.slug}</Td>
              <Td>
                <Badge tone="brand">{t(`deployment.${x.deploymentModel}`)}</Badge>
              </Td>
              <Td>{languageName(x.defaultLanguage)}</Td>
              <Td>
                <Badge tone={x.status === 'active' ? 'good' : 'neutral'}>{t(`admin.tenantStatus.${x.status}`)}</Badge>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

const STATUS_TONE = { active: 'good', invited: 'info', suspended: 'neutral' } as const

function Users() {
  const { t } = useTranslation()
  const me = useMe()
  const members = useMembers()
  const roles = useRoles().data ?? []
  const setStatus = useSetMemberStatus()
  const remove = useRemoveMember()
  const [open, setOpen] = useState(false)
  const failed = (message: string) => t('adminForms.actionFailed', { message })
  return (
    <div className="space-y-6">
      <Card>
        <InviteForm key={String(open)} open={open} onClose={() => setOpen(false)} />
        <CardHeader
          title={t('admin.usersTitle')}
          action={
            <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
              <Plus size={14} /> {t('admin.invite')}
            </Button>
          }
        />
        <Table>
          <thead>
            <tr>
              <Th>{t('admin.user')}</Th>
              <Th>{t('admin.roles')}</Th>
              <Th>{t('admin.lastSeen')}</Th>
              <Th>{t('admin.status')}</Th>
              <Th className="text-right" />
            </tr>
          </thead>
          <tbody>
            {(members.data ?? []).map((u) => (
              <tr key={u.id}>
                <Td>
                  <div className="font-medium text-text">{u.displayName}</div>
                  <div className="text-xs text-muted">{u.email}</div>
                </Td>
                <Td>
                  <div className="flex flex-wrap gap-1">
                    {u.roles.map((r) => {
                      const role = roles.find((x) => x.id === r.roleId)
                      const label = role ? roleLabel(t, role) : r.roleKey
                      return <Badge key={r.assignmentId}>{r.projectName ? `${label} · ${r.projectName}` : label}</Badge>
                    })}
                  </div>
                </Td>
                <Td>{u.lastLoginAt ? formatDateTime(u.lastLoginAt) : t('admin.never')}</Td>
                <Td>
                  <Badge tone={STATUS_TONE[u.status]}>{t(`admin.userStatus.${u.status}`)}</Badge>
                </Td>
                <Td className="text-right whitespace-nowrap">
                  {u.id !== me?.user.id && u.status !== 'invited' && (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={setStatus.isPending}
                        onClick={() =>
                          void run(
                            () =>
                              setStatus.mutateAsync({
                                id: u.id,
                                status: u.status === 'active' ? 'suspended' : 'active',
                              }),
                            t('adminForms.memberUpdated'),
                            failed,
                          )
                        }
                      >
                        {u.status === 'active' ? t('admin.suspend') : t('admin.reactivate')}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`${t('admin.removeMember')} ${u.displayName}`}
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(t('admin.confirmRemove', { name: u.displayName })))
                            void run(() => remove.mutateAsync(u.id), t('adminForms.memberRemoved'), failed)
                        }}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <Invitations roles={roles} />
    </div>
  )
}

const INVITATION_TONE = { pending: 'info', accepted: 'good', revoked: 'neutral', expired: 'warning' } as const

function Invitations({ roles }: { roles: Role[] }) {
  const { t } = useTranslation()
  const invitations = useInvitations().data ?? []
  const resend = useResendInvitation()
  const revoke = useRevokeInvitation()
  const failed = (message: string) => t('adminForms.actionFailed', { message })
  return (
    <Card>
      <CardHeader title={t('admin.invitationsTitle')} subtitle={t('admin.invitationsHint')} />
      {invitations.length === 0 ? (
        <CardBody>
          <EmptyState title={t('admin.empty')} />
        </CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('admin.user')}</Th>
              <Th>{t('admin.role')}</Th>
              <Th>{t('admin.expires')}</Th>
              <Th>{t('admin.status')}</Th>
              <Th className="text-right" />
            </tr>
          </thead>
          <tbody>
            {invitations.map((inv) => {
              const role = roles.find((r) => r.id === inv.roleId)
              return (
                <tr key={inv.id}>
                  <Td className="text-text">{inv.email}</Td>
                  <Td>{role ? roleLabel(t, role) : inv.roleKey}</Td>
                  <Td>{formatDateTime(inv.expiresAt)}</Td>
                  <Td>
                    <Badge tone={INVITATION_TONE[inv.status]}>{t(`admin.invitationStatus.${inv.status}`)}</Badge>
                  </Td>
                  <Td className="text-right whitespace-nowrap">
                    {inv.status === 'pending' && (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={resend.isPending}
                          onClick={() =>
                            void run(() => resend.mutateAsync(inv.id), t('adminForms.invitationResent'), failed)
                          }
                        >
                          <RotateCw size={14} /> {t('admin.resend')}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={revoke.isPending}
                          onClick={() =>
                            void run(() => revoke.mutateAsync(inv.id), t('adminForms.invitationRevoked'), failed)
                          }
                        >
                          {t('admin.revoke')}
                        </Button>
                      </>
                    )}
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function Roles() {
  const { t } = useTranslation()
  const rolesQuery = useRoles()
  const roles = useMemo(() => rolesQuery.data ?? [], [rolesQuery.data])
  const permissions = usePermissions().data ?? []
  const save = useSetRolePermissions()
  const deleteRole = useDeleteRole()
  const [open, setOpen] = useState(false)
  // Unsaved edits of the matrix (role id -> granted keys) on top of what the API returned.
  const [edits, setEdits] = useState<Record<string, string[]>>({})
  const granted = (r: Role) => edits[r.id] ?? r.permissions
  const changed = roles.filter(
    (r) => edits[r.id] && [...edits[r.id]].sort().join() !== [...r.permissions].sort().join(),
  )
  const failed = (message: string) => t('adminForms.actionFailed', { message })
  // The customer admin holds everything through inheritance; its column is shown but not edited.
  const editable = (r: Role) => r.key !== 'tenantAdmin'
  const toggle = (role: Role, permission: string) => {
    const current = granted(role)
    const next = current.includes(permission) ? current.filter((p) => p !== permission) : [...current, permission]
    setEdits({ ...edits, [role.id]: next })
  }
  return (
    <div className="space-y-6">
      <RoleForm key={String(open)} open={open} onClose={() => setOpen(false)} permissions={permissions} roles={roles} />
      <Card>
        <CardHeader
          title={t('admin.rolesTitle')}
          subtitle={t('admin.rolesHint')}
          action={
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus size={14} /> {t('admin.newRole')}
            </Button>
          }
        />
        <Table>
          <thead>
            <tr>
              <Th>{t('admin.role')}</Th>
              <Th>{t('admin.scope')}</Th>
              <Th className="text-right">{t('admin.members')}</Th>
              <Th className="text-right">{t('admin.permissions')}</Th>
              <Th className="text-right" />
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.id}>
                <Td className="font-medium text-text">{roleLabel(t, r)}</Td>
                <Td>
                  <Badge>{t(`admin.scopes.${r.scope}`)}</Badge>
                </Td>
                <Td className="text-right tabular">{r.members}</Td>
                <Td className="text-right tabular">{r.permissions.length}</Td>
                <Td className="text-right">
                  {!r.isSystem && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${t('admin.deleteRole')} ${roleLabel(t, r)}`}
                      disabled={deleteRole.isPending || r.members > 0}
                      onClick={() => void run(() => deleteRole.mutateAsync(r.id), t('adminForms.roleDeleted'), failed)}
                    >
                      <Trash2 size={14} />
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <Card>
        <CardHeader
          title={t('admin.matrixTitle')}
          subtitle={t('admin.matrixHint')}
          action={
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" disabled={changed.length === 0} onClick={() => setEdits({})}>
                {t('common.discard')}
              </Button>
              <Button
                size="sm"
                variant="primary"
                disabled={changed.length === 0 || save.isPending}
                onClick={() =>
                  void run(
                    async () => {
                      await Promise.all(changed.map((r) => save.mutateAsync({ id: r.id, permissions: granted(r) })))
                      setEdits({})
                    },
                    t('adminForms.matrixSaved'),
                    failed,
                  )
                }
              >
                {t('common.save')}
              </Button>
            </div>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <Th>{t('admin.permission')}</Th>
                {roles.map((r) => (
                  <Th key={r.id} className="text-center normal-case">
                    {roleLabel(t, r)}
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {permissions.map((p) => (
                <tr key={p.key}>
                  <Td className="font-mono text-xs text-text">{p.key}</Td>
                  {roles.map((r) => {
                    const applies = p.scopes.includes(r.scope)
                    const on = r.key === 'tenantAdmin' ? applies : granted(r).includes(p.key)
                    const label = `${p.key} · ${roleLabel(t, r)}`
                    return (
                      <Td key={r.id} className="p-0 text-center">
                        <button
                          onClick={() => toggle(r, p.key)}
                          disabled={!applies || !editable(r)}
                          aria-pressed={on}
                          aria-label={label}
                          title={!applies ? t('admin.notApplicable') : !editable(r) ? t('admin.adminHoldsAll') : label}
                          className="flex h-10 w-full items-center justify-center hover:bg-surface-2 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                        >
                          {on ? (
                            <Check size={14} className="text-good" />
                          ) : (
                            <span className="text-muted">{applies ? '·' : ''}</span>
                          )}
                        </button>
                      </Td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <CardBody className="space-y-2">
          <Notice tone="info">{t('admin.adminHoldsAll')}</Notice>
          <Notice tone="info">{t('admin.segregation')}</Notice>
        </CardBody>
      </Card>
    </div>
  )
}

// Design of the per-customer sign-in settings (M0b, D-27): shown with a notice, not connected yet.
function Authentication() {
  const { t } = useTranslation()
  const me = useMe()
  const [local, setLocal] = useState(true)
  const [sso, setSso] = useState(true)
  const [breached, setBreached] = useState(true)
  const [mfaAll, setMfaAll] = useState(true)
  const [methods, setMethods] = useState({ totp: true, passkey: true, recovery: true, sms: false })
  const [idpOpen, setIdpOpen] = useState(false)

  return (
    <div className="space-y-6">
      <Notice tone="info">{t('admin.auth.availableInM0b')}</Notice>
      <div className="flex flex-wrap items-center gap-3">
        <Select className="max-w-xs" value={me?.activeTenant?.id ?? ''} disabled aria-label={t('admin.tenant')}>
          {(me?.tenants ?? []).map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </Select>
        <span className="text-sm text-muted">{t('admin.auth.perTenant')}</span>
      </div>

      <Card>
        <CardHeader title={t('admin.auth.methods')} subtitle={t('admin.auth.methodsHint')} />
        <CardBody className="grid gap-4 md:grid-cols-2">
          <div className="rounded-md border border-border p-4">
            <Toggle
              checked={sso}
              onChange={setSso}
              label={<span className="font-medium">{t('admin.auth.sso')}</span>}
            />
            <p className="mt-2 text-sm text-text-2">{t('admin.auth.ssoHint')}</p>
          </div>
          <div className="rounded-md border border-border p-4">
            <Toggle
              checked={local}
              onChange={setLocal}
              label={<span className="font-medium">{t('admin.auth.local')}</span>}
            />
            <p className="mt-2 text-sm text-text-2">{t('admin.auth.localHint')}</p>
          </div>
          {!sso && !local && (
            <div className="md:col-span-2">
              <Notice tone="critical">{t('admin.auth.noMethod')}</Notice>
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t('admin.auth.providers')}
          subtitle={t('admin.auth.providersHint')}
          action={
            <Button size="sm" variant="primary" disabled={!sso} onClick={() => setIdpOpen(true)}>
              <Plus size={14} /> {t('admin.auth.addProvider')}
            </Button>
          }
        />
        <IdentityProviderForm open={idpOpen} onClose={() => setIdpOpen(false)} />
        <Table>
          <thead>
            <tr>
              <Th>{t('admin.auth.provider')}</Th>
              <Th>{t('admin.tenant')}</Th>
              <Th>{t('admin.auth.domains')}</Th>
              <Th>{t('admin.auth.enforced')}</Th>
              <Th>{t('admin.status')}</Th>
            </tr>
          </thead>
          <tbody>
            {identityProviders.map((p) => (
              <tr key={p.id}>
                <Td className="text-text">{p.type}</Td>
                <Td>{p.tenant}</Td>
                <Td className="font-mono text-xs">{p.domains.join(', ')}</Td>
                <Td>
                  {p.enforced ? (
                    <Badge tone="brand">{t('admin.auth.ssoOnly')}</Badge>
                  ) : (
                    <Badge>{t('admin.auth.optional')}</Badge>
                  )}
                </Td>
                <Td>
                  <Badge tone="good">{t('common.active')}</Badge>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('admin.auth.passwordPolicy')} subtitle={t('admin.auth.passwordPolicyHint')} />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field label={t('admin.auth.minLength')}>
              <Input type="number" defaultValue={12} disabled={!local} />
            </Field>
            <Field label={t('admin.auth.history')}>
              <Input type="number" defaultValue={10} disabled={!local} />
            </Field>
            <Field label={t('admin.auth.expiry')} hint={t('admin.auth.expiryHint')}>
              <Input type="number" defaultValue={0} disabled={!local} />
            </Field>
            <Field label={t('admin.auth.complexity')}>
              <Select defaultValue="all" disabled={!local}>
                <option value="all">{t('admin.auth.complexityAll')}</option>
                <option value="three">{t('admin.auth.complexityThree')}</option>
              </Select>
            </Field>
            <div className="sm:col-span-2">
              <Toggle checked={breached} onChange={setBreached} label={t('admin.auth.breached')} disabled={!local} />
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('admin.auth.mfaPolicy')} subtitle={t('admin.auth.mfaPolicyHint')} />
          <CardBody className="space-y-3">
            <Toggle checked={mfaAll} onChange={setMfaAll} label={t('admin.auth.mfaRequired')} />
            <div className="grid gap-2 pt-2 sm:grid-cols-2">
              <Toggle
                checked={methods.totp}
                onChange={(v) => setMethods({ ...methods, totp: v })}
                label={t('admin.auth.totp')}
              />
              <Toggle
                checked={methods.passkey}
                onChange={(v) => setMethods({ ...methods, passkey: v })}
                label={t('admin.auth.passkeys')}
              />
              <Toggle
                checked={methods.recovery}
                onChange={(v) => setMethods({ ...methods, recovery: v })}
                label={t('admin.auth.recoveryCodes')}
              />
              <Toggle
                checked={methods.sms}
                onChange={(v) => setMethods({ ...methods, sms: v })}
                label={t('admin.auth.sms')}
              />
            </div>
            {methods.sms && <Notice tone="warning">{t('admin.auth.smsWarning')}</Notice>}
            {!mfaAll && <Notice tone="critical">{t('admin.auth.mfaOffWarning')}</Notice>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('admin.auth.sessions')} />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field label={t('admin.auth.idleTimeout')}>
              <Input type="number" defaultValue={30} />
            </Field>
            <Field label={t('admin.auth.absoluteLifetime')}>
              <Input type="number" defaultValue={12} />
            </Field>
            <Field label={t('admin.auth.concurrent')}>
              <Input type="number" defaultValue={3} />
            </Field>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('admin.auth.lockout')} />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field label={t('admin.auth.failedAttempts')}>
              <Input type="number" defaultValue={5} />
            </Field>
            <Field label={t('admin.auth.lockoutMinutes')}>
              <Input type="number" defaultValue={15} />
            </Field>
          </CardBody>
        </Card>
      </div>
      <div className="flex justify-end">
        <Button variant="primary" onClick={() => toast(t('adminForms.authSaved'))}>
          <ShieldCheck size={16} /> {t('admin.auth.save')}
        </Button>
      </div>
    </div>
  )
}

function Security() {
  const { t } = useTranslation()
  const [ipList, setIpList] = useState(false)
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title={t('admin.securityData')} />
        <CardBody className="space-y-4">
          <Field label={t('admin.retention')}>
            <Select defaultValue="180">
              <option value="90">{t('admin.days', { count: 90 })}</option>
              <option value="180">{t('admin.days', { count: 180 })}</option>
              <option value="365">{t('admin.days', { count: 365 })}</option>
            </Select>
          </Field>
          <Field label={t('admin.encryptionKey')} hint={t('admin.encryptionKeyHint')}>
            <Input defaultValue="arn:aws:kms:us-east-1:…:key/andes-tenant" disabled />
          </Field>
          <Button variant="danger">{t('admin.verifiableDeletion')}</Button>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('admin.network')} />
        <CardBody className="space-y-4">
          <Toggle checked={ipList} onChange={setIpList} label={t('admin.ipAllowList')} />
          <Field label={t('admin.allowedRanges')}>
            <Input defaultValue="190.95.0.0/16, 10.20.0.0/16" disabled={!ipList} />
          </Field>
        </CardBody>
      </Card>
    </div>
  )
}

function Integrations() {
  const { t } = useTranslation()
  const items = [
    ['GitHub', true],
    ['GitLab', false],
    ['Azure DevOps', true],
    ['Jira', true],
    ['Figma', true],
  ] as const
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {items.map(([name, on]) => (
        <Card key={name}>
          <CardBody className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-text">{name}</div>
              <div className="text-xs text-muted">{t('admin.integrationHint')}</div>
            </div>
            <Button size="sm" variant={on ? 'secondary' : 'primary'}>
              {on ? t('common.configure') : t('common.connect')}
            </Button>
          </CardBody>
        </Card>
      ))}
    </div>
  )
}

const OUTCOME_TONE = { success: 'good', failure: 'warning', allowed: 'good', denied: 'critical' } as const

function Audit() {
  const { t } = useTranslation()
  // Pages of the log, newest first; each page gives the cursor of the next (older) one.
  const [cursors, setCursors] = useState<(number | null)[]>([null])
  const [chain, setChain] = useState<ChainStatus | null>(null)
  return (
    <Card>
      <CardHeader
        title={t('admin.auditTitle')}
        subtitle={t('admin.auditHint')}
        action={
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={async () => {
                try {
                  setChain(await verifyAuditChain())
                } catch (error) {
                  toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
                }
              }}
            >
              <ShieldCheck size={14} /> {t('admin.auditVerify')}
            </Button>
            <a
              href="/api/v1/audit/export"
              download
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-2"
            >
              <Download size={14} /> {t('usage.export')}
            </a>
          </div>
        }
      />
      {chain && (
        <CardBody>
          {chain.intact ? (
            <Notice tone="good">{t('admin.auditIntact', { count: chain.checked })}</Notice>
          ) : (
            <Notice tone="critical">
              {t('admin.auditBroken', { seq: chain.firstBrokenSeq, reason: chain.reason })}
            </Notice>
          )}
        </CardBody>
      )}
      <Table>
        <thead>
          <tr>
            <Th>{t('activity.time')}</Th>
            <Th>{t('activity.actor')}</Th>
            <Th>{t('activity.action')}</Th>
            <Th>{t('activity.target')}</Th>
            <Th>{t('admin.outcome')}</Th>
          </tr>
        </thead>
        <tbody>
          {cursors.map((before, i) => (
            <AuditPage
              key={before ?? 'first'}
              before={before}
              onNext={i === cursors.length - 1 ? (next) => setCursors([...cursors, next]) : undefined}
            />
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function AuditPage({ before, onNext }: { before: number | null; onNext?: (next: number) => void }) {
  const { t } = useTranslation()
  const page = useAudit(before).data
  if (!page) return null
  return (
    <>
      {page.items.map((e: AuditEntry) => (
        <tr key={e.id}>
          <Td>{formatDateTime(e.occurredAt)}</Td>
          <Td className="text-text">
            {e.actorLabel ?? e.actorId ?? '—'}
            {e.actorKind !== 'user' && <span className="ml-1 text-xs text-muted">({e.actorKind})</span>}
          </Td>
          <Td className="font-mono text-xs">{e.action}</Td>
          <Td className="font-mono text-xs">{e.target ?? '—'}</Td>
          <Td>
            <Badge tone={OUTCOME_TONE[e.outcome]}>{t(`admin.outcomes.${e.outcome}`)}</Badge>
          </Td>
        </tr>
      ))}
      {onNext && page.nextBefore != null && (
        <tr>
          <td className="border-b border-border px-4 py-3 text-center" colSpan={5}>
            <Button size="sm" variant="ghost" onClick={() => onNext(page.nextBefore as number)}>
              {t('admin.auditLoadMore')}
            </Button>
          </td>
        </tr>
      )}
    </>
  )
}
