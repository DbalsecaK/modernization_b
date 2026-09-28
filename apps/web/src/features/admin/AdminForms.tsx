import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { projects, tenants } from '@/mocks/data'
import type { Tenant } from '@/mocks/types'
import { Button, Field, Input, Select, Toggle } from '@/components/ui/primitives'
import { CheckboxGroup, Drawer, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'

const DEPLOYMENTS = ['sharedSaas', 'dedicatedSaas', 'customerCloud', 'onPrem'] as const
const PROJECT_ROLES = ['projectOwner', 'architect', 'analyst', 'businessReviewer', 'developer', 'observer'] as const
const TENANT_ROLES = ['tenantAdmin', 'auditor', 'finance'] as const

export function TenantForm({ open, onClose, onSave }: { open: boolean; onClose: () => void; onSave: (t: Tenant) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [deployment, setDeployment] = useState<Tenant['deployment']>('sharedSaas')
  const [language, setLanguage] = useState<'en' | 'es'>('en')
  const [region, setRegion] = useState('us-east-1')
  const [adminEmail, setAdminEmail] = useState('')
  const [domain, setDomain] = useState('')
  const [auth, setAuth] = useState<'sso' | 'local' | 'both'>('both')
  const valid = name.trim() && /^\S+@\S+\.\S+$/.test(adminEmail)

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
            disabled={!valid}
            onClick={() => {
              onSave({ id: `t${Date.now()}`, name, deployment, projects: 0, users: 1, monthCostUsd: 0, defaultLanguage: language })
              toast(t('adminForms.tenantCreated', { name }))
              onClose()
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
      <Field label={t('admin.deployment')} hint={t(`adminForms.deploymentHint.${deployment}`)}>
        <Select value={deployment} onChange={(e) => setDeployment(e.target.value as Tenant['deployment'])}>
          {DEPLOYMENTS.map((d) => (
            <option key={d} value={d}>
              {t(`deployment.${d}`)}
            </option>
          ))}
        </Select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('admin.defaultLanguage')}>
          <Select value={language} onChange={(e) => setLanguage(e.target.value as 'en' | 'es')}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </Field>
        <Field label={t('adminForms.dataRegion')}>
          <Select value={region} onChange={(e) => setRegion(e.target.value)}>
            {['us-east-1', 'sa-east-1', 'eastus2', 'brazilsouth', 'southamerica-east1'].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label={t('adminForms.firstAdmin')} hint={t('adminForms.firstAdminHint')}>
        <Input type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} placeholder="admin@coastalbank.example" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('adminForms.emailDomain')}>
          <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="coastalbank.example" />
        </Field>
        <Field label={t('adminForms.initialAuth')}>
          <Select value={auth} onChange={(e) => setAuth(e.target.value as typeof auth)}>
            <option value="both">{t('adminForms.authBoth')}</option>
            <option value="sso">{t('admin.auth.ssoOnly')}</option>
            <option value="local">{t('admin.auth.local')}</option>
          </Select>
        </Field>
      </div>
      <Notice tone="info">{t('adminForms.tenantProvisioning')}</Notice>
    </Drawer>
  )
}

export function InviteForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [emails, setEmails] = useState('')
  const [tenant, setTenant] = useState(tenants[0].id)
  const [tenantRoles, setTenantRoles] = useState<string[]>([])
  const [projectIds, setProjectIds] = useState<string[]>([])
  const [projectRole, setProjectRole] = useState<(typeof PROJECT_ROLES)[number]>('observer')
  const list = emails
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter(Boolean)
  const invalid = list.filter((e) => !/^\S+@\S+\.\S+$/.test(e))

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
          <Button
            variant="primary"
            disabled={list.length === 0 || invalid.length > 0}
            onClick={() => {
              toast(t('adminForms.invitesSent', { count: list.length }))
              onClose()
            }}
          >
            {t('adminForms.sendInvites', { count: list.length })}
          </Button>
        </>
      }
    >
      <Field label={t('adminForms.emails')} hint={t('adminForms.emailsHint')}>
        <Input value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="ana@andesbank.example, jose@andesbank.example" />
      </Field>
      {invalid.length > 0 && <Notice tone="critical">{t('adminForms.invalidEmails', { emails: invalid.join(', ') })}</Notice>}
      <Field label={t('admin.tenant')}>
        <Select value={tenant} onChange={(e) => setTenant(e.target.value)}>
          {tenants.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('adminForms.tenantRoles')} hint={t('adminForms.tenantRolesHint')}>
        <CheckboxGroup columns={3} options={TENANT_ROLES.map((r) => ({ id: r, label: t(`roles.${r}`) }))} value={tenantRoles} onChange={setTenantRoles} />
      </Field>
      <Field label={t('adminForms.projects')}>
        <CheckboxGroup
          columns={1}
          options={projects.filter((p) => p.tenantId === tenant).map((p) => ({ id: p.id, label: p.name }))}
          value={projectIds}
          onChange={setProjectIds}
        />
      </Field>
      {projectIds.length > 0 && (
        <Field label={t('adminForms.projectRole')}>
          <Select value={projectRole} onChange={(e) => setProjectRole(e.target.value as typeof projectRole)}>
            {PROJECT_ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`roles.${r}`)}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Notice tone="info">{t('adminForms.inviteFlow')}</Notice>
    </Drawer>
  )
}

export function RoleForm({ open, onClose, permissions }: { open: boolean; onClose: () => void; permissions: string[] }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'tenant' | 'project'>('project')
  const [granted, setGranted] = useState<string[]>([])
  const [base, setBase] = useState('')
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
            disabled={!name.trim() || granted.length === 0}
            onClick={() => {
              toast(t('adminForms.roleCreated', { name }))
              onClose()
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
          <Select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="tenant">{t('admin.scopes.tenant')}</option>
            <option value="project">{t('admin.scopes.project')}</option>
          </Select>
        </Field>
      </div>
      <Field label={t('adminForms.startFrom')}>
        <Select value={base} onChange={(e) => setBase(e.target.value)}>
          <option value="">{t('adminForms.blankRole')}</option>
          {[...TENANT_ROLES, ...PROJECT_ROLES].map((r) => (
            <option key={r} value={r}>
              {t(`roles.${r}`)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('admin.permissions')}>
        <CheckboxGroup columns={2} options={permissions.map((p) => ({ id: p, label: <span className="font-mono text-xs">{p}</span> }))} value={granted} onChange={setGranted} />
      </Field>
      <Notice tone="info">{t('admin.segregation')}</Notice>
    </Drawer>
  )
}

export function IdentityProviderForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [protocol, setProtocol] = useState<'oidc' | 'saml'>('oidc')
  const [preset, setPreset] = useState('entra')
  const [domains, setDomains] = useState('')
  const [ssoOnly, setSsoOnly] = useState(false)
  const [jit, setJit] = useState(true)
  const [scim, setScim] = useState(false)
  const [mappings, setMappings] = useState([{ group: 'SG-Modernization-Architects', role: 'architect' }])

  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={t('admin.auth.addProvider')}
      description={t('adminForms.idpHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!domains.trim()}
            onClick={() => {
              toast(t('adminForms.idpSaved'))
              onClose()
            }}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('adminForms.preset')}>
          <Select value={preset} onChange={(e) => setPreset(e.target.value)}>
            <option value="entra">Microsoft Entra ID</option>
            <option value="okta">Okta</option>
            <option value="google">Google Workspace</option>
            <option value="keycloak">Keycloak</option>
            <option value="other">{t('adminForms.otherProvider')}</option>
          </Select>
        </Field>
        <Field label={t('admin.auth.protocol')}>
          <Select value={protocol} onChange={(e) => setProtocol(e.target.value as 'oidc' | 'saml')}>
            <option value="oidc">OpenID Connect</option>
            <option value="saml">SAML 2.0</option>
          </Select>
        </Field>
      </div>
      {protocol === 'oidc' ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('admin.auth.issuer')} hint={t('admin.auth.issuerHint')}>
            <Input placeholder="https://login.microsoftonline.com/<tenant>/v2.0" />
          </Field>
          <Field label={t('admin.auth.clientId')}>
            <Input placeholder="00000000-0000-0000-0000-000000000000" />
          </Field>
          <Field label={t('admin.auth.clientSecret')} hint={t('admin.auth.secretHint')}>
            <Input type="password" placeholder="••••••••" />
          </Field>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('adminForms.metadataUrl')}>
            <Input placeholder="https://idp.example/metadata.xml" />
          </Field>
          <Field label={t('adminForms.entityId')}>
            <Input placeholder="https://idp.example/entity" />
          </Field>
        </div>
      )}
      <div className="rounded-md bg-surface-2 p-3 text-xs text-text-2">
        <div className="font-medium text-text">{t('adminForms.redirectUri')}</div>
        <code className="mt-1 block font-mono">https://auth.nexti-platform.example/realms/platform/broker/{preset}/endpoint</code>
      </div>
      <Field label={t('admin.auth.domains')} hint={t('adminForms.domainsHint')}>
        <Input value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="andesbank.example, andes.example" />
      </Field>
      <div className="space-y-3">
        <Toggle checked={ssoOnly} onChange={setSsoOnly} label={t('adminForms.enforceSso')} />
        <Toggle checked={jit} onChange={setJit} label={t('admin.auth.jit')} />
        <Toggle checked={scim} onChange={setScim} label={t('admin.auth.scim')} />
      </div>
      <Field label={t('admin.auth.groupMapping')} hint={t('admin.auth.groupMappingHint')}>
        <div className="space-y-2">
          {mappings.map((m, i) => (
            <div key={i} className="flex gap-2">
              <Input value={m.group} onChange={(e) => setMappings(mappings.map((x, j) => (j === i ? { ...x, group: e.target.value } : x)))} aria-label={t('adminForms.idpGroup')} />
              <Select value={m.role} onChange={(e) => setMappings(mappings.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))} aria-label={t('admin.role')}>
                {[...TENANT_ROLES, ...PROJECT_ROLES].map((r) => (
                  <option key={r} value={r}>
                    {t(`roles.${r}`)}
                  </option>
                ))}
              </Select>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setMappings([...mappings, { group: '', role: 'observer' }])}>
            {t('adminForms.addMapping')}
          </Button>
        </div>
      </Field>
      <Notice tone="info">{t('adminForms.keycloakNote')}</Notice>
    </Drawer>
  )
}
