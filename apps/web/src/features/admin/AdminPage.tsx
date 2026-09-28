import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Plus, ShieldCheck } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { formatDateTime, formatUsd } from '@/lib/format'
import { auditLog, identityProviders, permissionMatrix, roles, tenants, users } from '@/mocks/data'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, PageHeader, Select, Table, Tabs, Td, Th, Toggle } from '@/components/ui/primitives'
import { Notice } from '@/features/projects/NewProjectWizard'

const TABS = ['tenants', 'users', 'roles', 'authentication', 'security', 'integrations', 'audit'] as const

export function AdminPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useTab(TABS, 'tenants')
  return (
    <>
      <PageHeader title={t('admin.title')} description={t('admin.description')} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`admin.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {tab === 'tenants' && <Tenants />}
      {tab === 'users' && <Users />}
      {tab === 'roles' && <Roles />}
      {tab === 'authentication' && <Authentication />}
      {tab === 'security' && <Security />}
      {tab === 'integrations' && <Integrations />}
      {tab === 'audit' && <Audit />}
    </>
  )
}

function Tenants() {
  const { t, i18n } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('admin.tenantsTitle')} action={<Button size="sm" variant="primary"><Plus size={14} /> {t('admin.newTenant')}</Button>} />
      <Table>
        <thead>
          <tr>
            <Th>{t('admin.tenant')}</Th>
            <Th>{t('admin.deployment')}</Th>
            <Th>{t('admin.defaultLanguage')}</Th>
            <Th className="text-right">{t('admin.projects')}</Th>
            <Th className="text-right">{t('admin.users')}</Th>
            <Th className="text-right">{t('admin.monthSpend')}</Th>
          </tr>
        </thead>
        <tbody>
          {tenants.map((x) => (
            <tr key={x.id}>
              <Td className="font-medium text-text">{x.name}</Td>
              <Td>
                <Badge tone="brand">{t(`deployment.${x.deployment}`)}</Badge>
              </Td>
              <Td>{new Intl.DisplayNames([i18n.language], { type: 'language' }).of(x.defaultLanguage)}</Td>
              <Td className="text-right tabular">{x.projects}</Td>
              <Td className="text-right tabular">{x.users}</Td>
              <Td className="text-right tabular">{formatUsd(x.monthCostUsd)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function Users() {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('admin.usersTitle')} action={<Button size="sm" variant="primary"><Plus size={14} /> {t('admin.invite')}</Button>} />
      <Table>
        <thead>
          <tr>
            <Th>{t('admin.user')}</Th>
            <Th>{t('admin.tenant')}</Th>
            <Th>{t('admin.roles')}</Th>
            <Th>{t('admin.mfa')}</Th>
            <Th>{t('admin.lastSeen')}</Th>
            <Th>{t('admin.status')}</Th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <Td>
                <div className="font-medium text-text">{u.name}</div>
                <div className="text-xs text-muted">{u.email}</div>
              </Td>
              <Td>{u.tenant}</Td>
              <Td>
                <div className="flex flex-wrap gap-1">
                  {u.roles.map((r) => (
                    <Badge key={r}>{t(`roles.${r}`)}</Badge>
                  ))}
                </div>
              </Td>
              <Td>{u.mfa ? <Badge tone="good">{t('admin.mfaOn')}</Badge> : <Badge tone="warning">{t('admin.mfaPending')}</Badge>}</Td>
              <Td>{formatDateTime(u.lastSeen)}</Td>
              <Td>
                <Badge tone={u.status === 'active' ? 'good' : u.status === 'invited' ? 'info' : 'neutral'}>{t(`admin.userStatus.${u.status}`)}</Badge>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function Roles() {
  const { t } = useTranslation()
  const shown = ['superAdmin', 'tenantAdmin', 'projectOwner', 'architect', 'analyst', 'businessReviewer', 'developer', 'auditor', 'finance']
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title={t('admin.rolesTitle')} subtitle={t('admin.rolesHint')} action={<Button size="sm"><Plus size={14} /> {t('admin.newRole')}</Button>} />
        <Table>
          <thead>
            <tr>
              <Th>{t('admin.role')}</Th>
              <Th>{t('admin.scope')}</Th>
              <Th className="text-right">{t('admin.members')}</Th>
              <Th className="text-right">{t('admin.permissions')}</Th>
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.id}>
                <Td className="font-medium text-text">{t(`roles.${r.id}`)}</Td>
                <Td>
                  <Badge>{t(`admin.scopes.${r.scope}`)}</Badge>
                </Td>
                <Td className="text-right tabular">{r.members}</Td>
                <Td className="text-right tabular">{r.permissions}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <Card>
        <CardHeader title={t('admin.matrixTitle')} subtitle={t('admin.matrixHint')} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <Th>{t('admin.permission')}</Th>
                {shown.map((r) => (
                  <Th key={r} className="text-center normal-case">
                    {t(`roles.${r}`)}
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {permissionMatrix.map((p) => (
                <tr key={p.permission}>
                  <Td className="font-mono text-xs text-text">{p.permission}</Td>
                  {shown.map((r) => (
                    <Td key={r} className="text-center">
                      {p.roles.includes(r) ? <Check size={14} className="mx-auto text-good" aria-label={t('common.yes')} /> : <span className="text-muted" aria-label={t('common.no')}>·</span>}
                    </Td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <CardBody>
          <Notice tone="info">{t('admin.segregation')}</Notice>
        </CardBody>
      </Card>
    </div>
  )
}

function Authentication() {
  const { t } = useTranslation()
  const [local, setLocal] = useState(true)
  const [sso, setSso] = useState(true)
  const [breached, setBreached] = useState(true)
  const [mfaAll, setMfaAll] = useState(true)
  const [methods, setMethods] = useState({ totp: true, passkey: true, recovery: true, sms: false })
  const [jit, setJit] = useState(true)
  const [scim, setScim] = useState(false)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Select className="max-w-xs" defaultValue="t1" aria-label={t('admin.tenant')}>
          {tenants.map((x) => (
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
            <Toggle checked={sso} onChange={setSso} label={<span className="font-medium">{t('admin.auth.sso')}</span>} />
            <p className="mt-2 text-sm text-text-2">{t('admin.auth.ssoHint')}</p>
          </div>
          <div className="rounded-md border border-border p-4">
            <Toggle checked={local} onChange={setLocal} label={<span className="font-medium">{t('admin.auth.local')}</span>} />
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
        <CardHeader title={t('admin.auth.providers')} subtitle={t('admin.auth.providersHint')} action={<Button size="sm" variant="primary" disabled={!sso}><Plus size={14} /> {t('admin.auth.addProvider')}</Button>} />
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
                <Td>{p.enforced ? <Badge tone="brand">{t('admin.auth.ssoOnly')}</Badge> : <Badge>{t('admin.auth.optional')}</Badge>}</Td>
                <Td>
                  <Badge tone="good">{t('common.active')}</Badge>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <CardBody className="grid gap-4 border-t border-border md:grid-cols-2">
          <Field label={t('admin.auth.protocol')}>
            <Select defaultValue="oidc">
              <option value="oidc">OpenID Connect</option>
              <option value="saml">SAML 2.0</option>
            </Select>
          </Field>
          <Field label={t('admin.auth.issuer')} hint={t('admin.auth.issuerHint')}>
            <Input placeholder="https://login.microsoftonline.com/<tenant>/v2.0" />
          </Field>
          <Field label={t('admin.auth.clientId')}>
            <Input placeholder="00000000-0000-0000-0000-000000000000" />
          </Field>
          <Field label={t('admin.auth.clientSecret')} hint={t('admin.auth.secretHint')}>
            <Input type="password" placeholder="••••••••" />
          </Field>
          <Field label={t('admin.auth.groupMapping')} hint={t('admin.auth.groupMappingHint')}>
            <Input placeholder="SG-Modernization-Architects → architect" />
          </Field>
          <div className="space-y-3 pt-6">
            <Toggle checked={jit} onChange={setJit} label={t('admin.auth.jit')} />
            <Toggle checked={scim} onChange={setScim} label={t('admin.auth.scim')} />
          </div>
        </CardBody>
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
              <Toggle checked={methods.totp} onChange={(v) => setMethods({ ...methods, totp: v })} label={t('admin.auth.totp')} />
              <Toggle checked={methods.passkey} onChange={(v) => setMethods({ ...methods, passkey: v })} label={t('admin.auth.passkeys')} />
              <Toggle checked={methods.recovery} onChange={(v) => setMethods({ ...methods, recovery: v })} label={t('admin.auth.recoveryCodes')} />
              <Toggle checked={methods.sms} onChange={(v) => setMethods({ ...methods, sms: v })} label={t('admin.auth.sms')} />
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
        <Button variant="primary">
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

function Audit() {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('admin.auditTitle')} subtitle={t('admin.auditHint')} action={<Button size="sm">{t('usage.export')}</Button>} />
      <Table>
        <thead>
          <tr>
            <Th>{t('activity.time')}</Th>
            <Th>{t('admin.tenant')}</Th>
            <Th>{t('activity.actor')}</Th>
            <Th>{t('activity.action')}</Th>
            <Th>{t('activity.target')}</Th>
          </tr>
        </thead>
        <tbody>
          {auditLog.map((e) => (
            <tr key={e.id}>
              <Td>{formatDateTime(e.time)}</Td>
              <Td>{e.tenant}</Td>
              <Td className="text-text">{e.actor}</Td>
              <Td className="font-mono text-xs">{e.action}</Td>
              <Td>{e.target}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}
