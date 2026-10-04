import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  roleLabel,
  useAssignRole,
  useCreateRole,
  useCreateTenant,
  useInvite,
  useProjects,
  useRenameRole,
  useRoles,
  useUpdateTenant,
  type Member,
  type Permission,
  type Role,
  type Tenant,
} from '@/api/admin'
import { ApiError } from '@/api/client'
import { Button, Field, Input, Select } from '@/components/ui/primitives'
import { CheckboxGroup, Drawer, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'

const DEPLOYMENTS = ['sharedSaas', 'dedicatedSaas', 'customerCloud', 'onPrem'] as const
type Deployment = (typeof DEPLOYMENTS)[number]
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error)
}

function slugify(name: string): string {
  return name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
}

export function TenantForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateTenant()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugEdited, setSlugEdited] = useState(false)
  const [deployment, setDeployment] = useState<Deployment>('sharedSaas')
  const [language, setLanguage] = useState<'en' | 'es'>('en')
  const effectiveSlug = slugEdited ? slug : slugify(name)
  const valid = name.trim().length > 0 && /^[a-z0-9][a-z0-9-]{1,62}$/.test(effectiveSlug)

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('admin.newTenant')}
      description={t('adminForms.tenantHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!valid || create.isPending}
            onClick={async () => {
              try {
                await create.mutateAsync({
                  name,
                  slug: effectiveSlug,
                  deploymentModel: deployment,
                  defaultLanguage: language,
                })
                toast(t('adminForms.tenantCreated', { name }))
                onClose()
              } catch (error) {
                toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
              }
            }}
          >
            {t('adminForms.createTenant')}
          </Button>
        </>
      }
    >
      <Field label={t('adminForms.tenantName')}>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Coastal Savings Bank" />
      </Field>
      <Field label={t('adminForms.tenantSlug')} hint={t('adminForms.tenantSlugHint')}>
        <Input
          value={effectiveSlug}
          onChange={(e) => {
            setSlugEdited(true)
            setSlug(e.target.value)
          }}
          placeholder="coastal-savings"
        />
      </Field>
      <Field label={t('admin.deployment')} hint={t(`adminForms.deploymentHint.${deployment}`)}>
        <Select value={deployment} onChange={(e) => setDeployment(e.target.value as Deployment)}>
          {DEPLOYMENTS.map((d) => (
            <option key={d} value={d}>
              {t(`deployment.${d}`)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('admin.defaultLanguage')}>
        <Select value={language} onChange={(e) => setLanguage(e.target.value as 'en' | 'es')}>
          <option value="en">English</option>
          <option value="es">Español</option>
        </Select>
      </Field>
    </Drawer>
  )
}

export function InviteForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const roles = useRoles().data ?? []
  const projects = useProjects().data ?? []
  const invite = useInvite()
  const [emails, setEmails] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [roleId, setRoleId] = useState('')
  const [projectId, setProjectId] = useState('')
  const list = emails
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter(Boolean)
  const invalid = list.filter((e) => !EMAIL.test(e))
  const role = roles.find((r) => r.id === roleId)
  const needsProject = role?.scope === 'project'
  const valid = list.length > 0 && invalid.length === 0 && !!role && (!needsProject || !!projectId)

  async function send() {
    const failed: string[] = []
    for (const email of list) {
      try {
        await invite.mutateAsync({
          email,
          displayName: list.length === 1 && displayName.trim() ? displayName.trim() : null,
          roleId,
          projectId: needsProject ? projectId : null,
        })
      } catch (error) {
        failed.push(`${email} (${errorMessage(error)})`)
      }
    }
    const sent = list.length - failed.length
    toast(
      failed.length
        ? t('adminForms.invitePartial', { sent, errors: failed.join(', ') })
        : t('adminForms.invitesSent', { count: sent }),
    )
    if (!failed.length) onClose()
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('admin.invite')}
      description={t('adminForms.inviteHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={!valid || invite.isPending} onClick={() => void send()}>
            {t('adminForms.sendInvites', { count: list.length })}
          </Button>
        </>
      }
    >
      <Field label={t('adminForms.emails')} hint={t('adminForms.emailsHint')}>
        <Input
          value={emails}
          onChange={(e) => setEmails(e.target.value)}
          placeholder="ana@andesbank.example, jose@andesbank.example"
        />
      </Field>
      {invalid.length > 0 && (
        <Notice tone="critical">{t('adminForms.invalidEmails', { emails: invalid.join(', ') })}</Notice>
      )}
      {list.length === 1 && (
        <Field label={t('adminForms.displayName')}>
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>
      )}
      <Field label={t('adminForms.role')}>
        <Select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
          <option value="" disabled>
            —
          </option>
          {(['tenant', 'project'] as const).map((scope) => (
            <optgroup key={scope} label={t(`admin.scopes.${scope}`)}>
              {roles
                .filter((r) => r.scope === scope)
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {roleLabel(t, r)}
                  </option>
                ))}
            </optgroup>
          ))}
        </Select>
      </Field>
      {needsProject && (
        <Field label={t('adminForms.project')}>
          <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="" disabled>
              —
            </option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Notice tone="info">{t('adminForms.inviteFlow')}</Notice>
    </Drawer>
  )
}

function roleKeyFrom(name: string): string {
  const words = name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^A-Za-z0-9 ]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  const key = words.map((w, i) => (i === 0 ? w.toLowerCase() : w[0].toUpperCase() + w.slice(1).toLowerCase())).join('')
  return /^[a-zA-Z]/.test(key) ? key.slice(0, 63) : `role${key}`.slice(0, 63)
}

export function RoleForm({
  open,
  onClose,
  permissions,
  roles,
}: {
  open: boolean
  onClose: () => void
  permissions: Permission[]
  roles: Role[]
}) {
  const { t } = useTranslation()
  const create = useCreateRole()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'tenant' | 'project'>('project')
  const [granted, setGranted] = useState<string[]>([])
  const [base, setBase] = useState('')
  const available = permissions.filter((p) => p.scopes.includes(scope))
  const key = roleKeyFrom(name)
  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={t('admin.newRole')}
      description={t('admin.rolesHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim() || key.length < 2 || create.isPending}
            onClick={async () => {
              try {
                await create.mutateAsync({
                  key,
                  name: name.trim(),
                  scope,
                  permissions: granted.filter((g) => available.some((p) => p.key === g)),
                })
                toast(t('adminForms.roleCreated', { name }))
                onClose()
              } catch (error) {
                toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
              }
            }}
          >
            {t('adminForms.createRole')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('adminForms.roleName')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Credit analyst" />
        </Field>
        <Field label={t('admin.scope')}>
          <Select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value as typeof scope)
              setBase('')
              setGranted([])
            }}
          >
            <option value="tenant">{t('admin.scopes.tenant')}</option>
            <option value="project">{t('admin.scopes.project')}</option>
          </Select>
        </Field>
      </div>
      <Field label={t('adminForms.startFrom')}>
        <Select
          value={base}
          onChange={(e) => {
            setBase(e.target.value)
            setGranted(roles.find((r) => r.id === e.target.value)?.permissions ?? [])
          }}
        >
          <option value="">{t('adminForms.blankRole')}</option>
          {roles
            .filter((r) => r.scope === scope)
            .map((r) => (
              <option key={r.id} value={r.id}>
                {roleLabel(t, r)}
              </option>
            ))}
        </Select>
      </Field>
      <Field label={t('admin.permissions')}>
        <CheckboxGroup
          columns={2}
          options={available.map((p) => ({ id: p.key, label: <span className="font-mono text-xs">{p.key}</span> }))}
          value={granted}
          onChange={setGranted}
        />
      </Field>
      <Notice tone="info">{t('admin.segregation')}</Notice>
    </Drawer>
  )
}

export function TenantEditForm({ open, onClose, tenant }: { open: boolean; onClose: () => void; tenant: Tenant }) {
  const { t } = useTranslation()
  const update = useUpdateTenant()
  const [name, setName] = useState(tenant.name)
  const [deployment, setDeployment] = useState<Deployment>(tenant.deploymentModel as Deployment)
  const [language, setLanguage] = useState<'en' | 'es'>(tenant.defaultLanguage as 'en' | 'es')
  const [status, setStatus] = useState<'active' | 'suspended'>(tenant.status as 'active' | 'suspended')
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('adminForms.editTenant', { name: tenant.name })}
      description={t('adminForms.editTenantHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim() || update.isPending}
            onClick={async () => {
              try {
                await update.mutateAsync({
                  id: tenant.id,
                  name: name.trim(),
                  deploymentModel: deployment,
                  defaultLanguage: language,
                  status,
                })
                toast(t('adminForms.tenantUpdated', { name: name.trim() }))
                onClose()
              } catch (error) {
                toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
              }
            }}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <Field label={t('adminForms.tenantName')}>
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={t('admin.deployment')} hint={t(`adminForms.deploymentHint.${deployment}`)}>
        <Select value={deployment} onChange={(e) => setDeployment(e.target.value as Deployment)}>
          {DEPLOYMENTS.map((d) => (
            <option key={d} value={d}>
              {t(`deployment.${d}`)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('admin.defaultLanguage')}>
        <Select value={language} onChange={(e) => setLanguage(e.target.value as 'en' | 'es')}>
          <option value="en">English</option>
          <option value="es">Español</option>
        </Select>
      </Field>
      <Field label={t('admin.status')} hint={t('adminForms.tenantStatusHint')}>
        <Select value={status} onChange={(e) => setStatus(e.target.value as 'active' | 'suspended')}>
          <option value="active">{t('admin.tenantStatus.active')}</option>
          <option value="suspended">{t('admin.tenantStatus.suspended')}</option>
        </Select>
      </Field>
    </Drawer>
  )
}

export function AssignRoleForm({ open, onClose, member }: { open: boolean; onClose: () => void; member: Member }) {
  const { t } = useTranslation()
  const roles = useRoles().data ?? []
  const projects = useProjects().data ?? []
  const assign = useAssignRole()
  const [roleId, setRoleId] = useState('')
  const [projectId, setProjectId] = useState('')
  const role = roles.find((r) => r.id === roleId)
  const needsProject = role?.scope === 'project'
  const valid = !!role && (!needsProject || !!projectId)
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('adminForms.assignRoleTitle', { name: member.displayName })}
      description={t('adminForms.assignRoleHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!valid || assign.isPending}
            onClick={async () => {
              try {
                await assign.mutateAsync({ userId: member.id, roleId, projectId: needsProject ? projectId : null })
                toast(t('adminForms.roleAssigned', { name: member.displayName }))
                onClose()
              } catch (error) {
                toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
              }
            }}
          >
            {t('adminForms.assignRole')}
          </Button>
        </>
      }
    >
      <Field label={t('adminForms.role')}>
        <Select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
          <option value="" disabled>
            —
          </option>
          {(['tenant', 'project'] as const).map((scope) => (
            <optgroup key={scope} label={t(`admin.scopes.${scope}`)}>
              {roles
                .filter((r) => r.scope === scope)
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {roleLabel(t, r)}
                  </option>
                ))}
            </optgroup>
          ))}
        </Select>
      </Field>
      {needsProject && (
        <Field label={t('adminForms.project')}>
          <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="" disabled>
              —
            </option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Notice tone="info">{t('admin.segregation')}</Notice>
    </Drawer>
  )
}

export function RoleRenameForm({ open, onClose, role }: { open: boolean; onClose: () => void; role: Role }) {
  const { t } = useTranslation()
  const rename = useRenameRole()
  const [name, setName] = useState(role.name)
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('adminForms.renameRole')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim() || name.trim() === role.name || rename.isPending}
            onClick={async () => {
              try {
                await rename.mutateAsync({ id: role.id, name: name.trim() })
                toast(t('adminForms.roleRenamed', { name: name.trim() }))
                onClose()
              } catch (error) {
                toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
              }
            }}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <Field label={t('adminForms.roleName')}>
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
    </Drawer>
  )
}
