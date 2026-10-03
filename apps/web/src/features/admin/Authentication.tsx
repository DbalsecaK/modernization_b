import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, KeyRound, Pencil, Plus, RotateCw, ShieldCheck, Trash2 } from 'lucide-react'
import { roleLabel, useRoles } from '@/api/admin'
import {
  parseDomains,
  PRESETS,
  toGroupRoles,
  useApplyProvider,
  useCreateProvider,
  useCreateScimAccess,
  useDeleteProvider,
  useIdentity,
  useRevokeScimAccess,
  useSaveIdentity,
  useScimAccess,
  useUpdateProvider,
  type Identity,
  type IdentityProvider,
  type Preset,
} from '@/api/identity'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Select,
  Table,
  Td,
  Th,
  Toggle,
} from '@/components/ui/primitives'
import { Drawer, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'
import { formatDateTime } from '@/lib/format'
import { errorMessage } from './AdminForms'

const STATUS_TONE = { active: 'good', pending: 'neutral', failed: 'critical' } as const

/** Administration → Authentication (M0b, ADR-0022): methods, MFA, domains and identity providers of the tenant. */
export function Authentication() {
  const { t } = useTranslation()
  const identity = useIdentity()
  const data = identity.data
  if (identity.isLoading) return <p className="text-sm text-muted">{t('common.loading')}</p>
  if (identity.error || !data) return <Notice tone="critical">{errorMessage(identity.error)}</Notice>
  // The form starts from what the server has; a saved change gives it a new starting point.
  const version = [data.localAccounts, data.sso, data.mfaRequired, ...data.domains].join('|')
  return <AuthenticationForm key={version} data={data} />
}

function AuthenticationForm({ data }: { data: Identity }) {
  const { t } = useTranslation()
  const save = useSaveIdentity()
  const apply = useApplyProvider()
  const remove = useDeleteProvider()
  const [local, setLocal] = useState(data.localAccounts)
  const [sso, setSso] = useState(data.sso)
  const [mfa, setMfa] = useState(data.mfaRequired)
  const [domains, setDomains] = useState(data.domains.join(', '))
  const [editing, setEditing] = useState<IdentityProvider | 'new' | null>(null)

  const failed = (message: string) => t('adminForms.actionFailed', { message })
  const submit = async () => {
    try {
      await save.mutateAsync({ localAccounts: local, sso, mfaRequired: mfa, domains: parseDomains(domains) })
      toast(t('adminForms.authSaved'))
    } catch (error) {
      toast(failed(errorMessage(error)))
    }
  }

  return (
    <div className="space-y-6">
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
          <div className="md:col-span-2">
            <Field label={t('admin.auth.tenantDomains')} hint={t('admin.auth.tenantDomainsHint')}>
              <Input value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="andesbank.example" />
            </Field>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t('admin.auth.providers')}
          subtitle={t('admin.auth.providersHint')}
          action={
            <Button size="sm" variant="primary" onClick={() => setEditing('new')}>
              <Plus size={14} /> {t('admin.auth.addProvider')}
            </Button>
          }
        />
        {editing && (
          <ProviderForm
            key={editing === 'new' ? 'new' : editing.id}
            initial={editing === 'new' ? undefined : editing}
            onClose={() => setEditing(null)}
          />
        )}
        {data.providers.length === 0 ? (
          <CardBody>
            <EmptyState title={t('admin.auth.noProviders')} description={t('admin.auth.noProvidersHint')} />
          </CardBody>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t('admin.auth.provider')}</Th>
                <Th>{t('admin.auth.domains')}</Th>
                <Th>{t('admin.auth.enforced')}</Th>
                <Th>{t('admin.status')}</Th>
                <Th>
                  <span className="sr-only">{t('admin.auth.actions')}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {data.providers.map((p) => (
                <tr key={p.id}>
                  <Td className="text-text">
                    <div className="font-medium">{p.displayName}</div>
                    <div className="font-mono text-xs text-muted">
                      {p.protocol.toUpperCase()} · {p.alias}
                    </div>
                  </Td>
                  <Td className="font-mono text-xs">{p.domains.join(', ') || '—'}</Td>
                  <Td>
                    {p.ssoOnly ? (
                      <Badge tone="brand">{t('admin.auth.ssoOnly')}</Badge>
                    ) : (
                      <Badge>{t('admin.auth.optional')}</Badge>
                    )}
                  </Td>
                  <Td>
                    <Badge tone={STATUS_TONE[p.status]}>{t(`admin.auth.status.${p.status}`)}</Badge>
                    {p.lastError && <div className="mt-1 max-w-xs text-xs text-critical-ink">{p.lastError}</div>}
                  </Td>
                  <Td className="whitespace-nowrap text-right">
                    <Button size="sm" variant="ghost" aria-label={t('common.edit')} onClick={() => setEditing(p)}>
                      <Pencil size={14} />
                    </Button>
                    {p.status !== 'active' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('admin.auth.applyAgain')}
                        onClick={() =>
                          apply.mutateAsync(p.id).then(
                            (r) => toast(t(`admin.auth.applied.${r.status}`)),
                            (e) => toast(failed(errorMessage(e))),
                          )
                        }
                      >
                        <RotateCw size={14} />
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t('common.remove')}
                      onClick={() =>
                        remove.mutateAsync(p.id).then(
                          () => toast(t('admin.auth.providerDeleted')),
                          (e) => toast(failed(errorMessage(e))),
                        )
                      }
                    >
                      <Trash2 size={14} />
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <ScimCard />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('admin.auth.mfaPolicy')} subtitle={t('admin.auth.mfaPolicyHint')} />
          <CardBody className="space-y-3">
            <Toggle checked={mfa} onChange={setMfa} label={t('admin.auth.mfaRequired')} />
            <div className="flex flex-wrap gap-2 pt-1">
              <Badge>{t('admin.auth.totp')}</Badge>
              <Badge>{t('admin.auth.passkeys')}</Badge>
              <Badge>{t('admin.auth.recoveryCodes')}</Badge>
            </div>
            <p className="text-sm text-text-2">{t('admin.auth.mfaSsoNote')}</p>
            {!mfa && local && <Notice tone="warning">{t('admin.auth.mfaOffWarning')}</Notice>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('admin.auth.realmPolicy')} subtitle={t('admin.auth.realmPolicyHint')} />
          <CardBody>
            {data.realm ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">{t('admin.auth.passwordPolicy')}</dt>
                <dd className="font-mono text-xs">{data.realm.passwordPolicy || '—'}</dd>
                <dt className="text-muted">{t('admin.auth.failedAttempts')}</dt>
                <dd>{data.realm.lockoutFailures}</dd>
                <dt className="text-muted">{t('admin.auth.lockoutMinutes')}</dt>
                <dd>{data.realm.lockoutMinutes}</dd>
                <dt className="text-muted">{t('admin.auth.idleTimeout')}</dt>
                <dd>{data.realm.sessionIdleMinutes}</dd>
                <dt className="text-muted">{t('admin.auth.absoluteLifetime')}</dt>
                <dd>{data.realm.sessionMaxHours}</dd>
              </dl>
            ) : (
              <p className="text-sm text-muted">{t('admin.auth.realmUnavailable')}</p>
            )}
          </CardBody>
        </Card>
      </div>
      <div className="flex justify-end">
        <Button variant="primary" disabled={(!sso && !local) || save.isPending} onClick={submit}>
          <ShieldCheck size={16} /> {t('admin.auth.save')}
        </Button>
      </div>
    </div>
  )
}

/** A new identity provider, or a change to one. The client secret is sent once; empty means "keep the current". */
function ProviderForm({ initial, onClose }: { initial?: IdentityProvider; onClose: () => void }) {
  const { t } = useTranslation()
  const roles = (useRoles().data ?? []).filter((r) => r.scope === 'tenant')
  const create = useCreateProvider()
  const update = useUpdateProvider()
  const settings = initial?.settings ?? {}
  const [preset, setPreset] = useState<Preset>('entra')
  const [name, setName] = useState(initial?.displayName ?? '')
  const [protocol, setProtocol] = useState<'oidc' | 'saml'>(initial?.protocol ?? 'oidc')
  const [values, setValues] = useState<Record<string, string>>(settings)
  const [secret, setSecret] = useState('')
  const [domains, setDomains] = useState((initial?.domains ?? []).join(', '))
  const [ssoOnly, setSsoOnly] = useState(initial?.ssoOnly ?? false)
  const [jit, setJit] = useState(initial?.jit ?? true)
  const [defaultRole, setDefaultRole] = useState(initial?.defaultRole ?? '')
  const [mappings, setMappings] = useState(
    Object.entries(initial?.groupRoles ?? {}).map(([group, role]) => ({ group, role })),
  )
  const set = (key: string, value: string) => setValues({ ...values, [key]: value })
  const pending = create.isPending || update.isPending

  const submit = async () => {
    const body = {
      displayName: name,
      settings: Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim())),
      domains: parseDomains(domains),
      ssoOnly,
      jit,
      groupRoles: toGroupRoles(mappings),
      defaultRole: defaultRole || null,
      ...(secret ? { clientSecret: secret } : {}),
    }
    try {
      const saved = initial
        ? await update.mutateAsync({ id: initial.id, ...body })
        : await create.mutateAsync({ ...body, protocol })
      toast(t(`admin.auth.applied.${saved.status}`))
      onClose()
    } catch (error) {
      toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
    }
  }

  return (
    <Drawer
      open
      onClose={onClose}
      wide
      title={initial ? t('admin.auth.editProvider') : t('admin.auth.addProvider')}
      description={t('adminForms.idpHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={!name.trim() || pending} onClick={submit}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('admin.auth.providerName')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Microsoft Entra ID" />
        </Field>
        <Field label={t('admin.auth.protocol')}>
          <Select
            value={protocol}
            disabled={!!initial}
            onChange={(e) => setProtocol(e.target.value as 'oidc' | 'saml')}
          >
            <option value="oidc">OpenID Connect</option>
            <option value="saml">SAML 2.0</option>
          </Select>
        </Field>
      </div>
      {protocol === 'oidc' ? (
        <>
          {!initial && (
            <Field label={t('adminForms.preset')}>
              <Select
                value={preset}
                onChange={(e) => {
                  const next = e.target.value as Preset
                  setPreset(next)
                  setValues({ ...values, issuer: PRESETS[next].issuer, scopes: PRESETS[next].scopes })
                }}
              >
                <option value="entra">Microsoft Entra ID</option>
                <option value="okta">Okta</option>
                <option value="google">Google Workspace</option>
                <option value="other">{t('adminForms.otherProvider')}</option>
              </Select>
            </Field>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('admin.auth.issuer')} hint={t('admin.auth.issuerHint')}>
              <Input
                value={values.issuer ?? ''}
                onChange={(e) => set('issuer', e.target.value)}
                placeholder={PRESETS[preset].issuer}
              />
            </Field>
            <Field label={t('admin.auth.clientId')}>
              <Input value={values.client_id ?? ''} onChange={(e) => set('client_id', e.target.value)} />
            </Field>
            <Field
              label={t('admin.auth.clientSecret')}
              hint={t(initial ? 'admin.auth.keepSecret' : 'admin.auth.secretHint')}
            >
              <Input
                type="password"
                autoComplete="new-password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
              />
            </Field>
            <Field label={t('admin.auth.groupsClaim')}>
              <Input
                value={values.groups_claim ?? ''}
                onChange={(e) => set('groups_claim', e.target.value)}
                placeholder="groups"
              />
            </Field>
          </div>
          <details className="rounded-md border border-border p-3 text-sm">
            <summary className="cursor-pointer font-medium">{t('admin.auth.endpoints')}</summary>
            <p className="mt-2 text-xs text-text-2">{t('admin.auth.endpointsHint')}</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {['authorization_url', 'token_url', 'jwks_url', 'userinfo_url'].map((key) => (
                <Field key={key} label={t(`admin.auth.endpoint.${key}`)}>
                  <Input value={values[key] ?? ''} onChange={(e) => set(key, e.target.value)} />
                </Field>
              ))}
            </div>
          </details>
        </>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('adminForms.metadataUrl')}>
            <Input
              value={values.metadata_url ?? ''}
              onChange={(e) => set('metadata_url', e.target.value)}
              placeholder="https://idp.example/metadata.xml"
            />
          </Field>
          <Field label={t('adminForms.entityId')}>
            <Input value={values.entity_id ?? ''} onChange={(e) => set('entity_id', e.target.value)} />
          </Field>
          <Field label={t('admin.auth.groupsAttribute')}>
            <Input
              value={values.groups_attribute ?? ''}
              onChange={(e) => set('groups_attribute', e.target.value)}
              placeholder="groups"
            />
          </Field>
        </div>
      )}
      {initial && (
        <div className="rounded-md bg-surface-2 p-3 text-xs text-text-2">
          <div className="font-medium text-text">{t('adminForms.redirectUri')}</div>
          <code className="mt-1 block break-all font-mono">{initial.redirectUri}</code>
        </div>
      )}
      <Field label={t('admin.auth.domains')} hint={t('adminForms.domainsHint')}>
        <Input value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="andesbank.example" />
      </Field>
      <div className="space-y-3">
        <Toggle checked={ssoOnly} onChange={setSsoOnly} label={t('adminForms.enforceSso')} />
        <Toggle checked={jit} onChange={setJit} label={t('admin.auth.jit')} />
      </div>
      <Field label={t('admin.auth.groupMapping')} hint={t('admin.auth.groupMappingHint')}>
        <div className="space-y-2">
          {mappings.map((m, i) => (
            <div key={i} className="flex gap-2">
              <Input
                value={m.group}
                onChange={(e) => setMappings(mappings.map((x, j) => (j === i ? { ...x, group: e.target.value } : x)))}
                aria-label={t('adminForms.idpGroup')}
              />
              <Select
                value={m.role}
                onChange={(e) => setMappings(mappings.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))}
                aria-label={t('admin.role')}
              >
                <option value="">—</option>
                {roles.map((r) => (
                  <option key={r.key} value={r.key}>
                    {roleLabel(t, r)}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                variant="ghost"
                aria-label={t('common.remove')}
                onClick={() => setMappings(mappings.filter((_, j) => j !== i))}
              >
                <Trash2 size={14} />
              </Button>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setMappings([...mappings, { group: '', role: '' }])}>
            {t('adminForms.addMapping')}
          </Button>
        </div>
      </Field>
      <Field label={t('admin.auth.defaultRole')} hint={t('admin.auth.defaultRoleHint')}>
        <Select value={defaultRole} onChange={(e) => setDefaultRole(e.target.value)}>
          <option value="">{t('admin.auth.noDefaultRole')}</option>
          {roles.map((r) => (
            <option key={r.key} value={r.key}>
              {roleLabel(t, r)}
            </option>
          ))}
        </Select>
      </Field>
      <Notice tone="info">{t('adminForms.keycloakNote')}</Notice>
    </Drawer>
  )
}

/** SCIM 2.0 (M16, ADR-0031): the base URL and the bearer the customer's identity provider uses to provision people. */
function ScimCard() {
  const { t } = useTranslation()
  const access = useScimAccess()
  const create = useCreateScimAccess()
  const revoke = useRevokeScimAccess()
  // The new bearer lives only in this component's state, until "Done": the API never returns it again.
  const [shown, setShown] = useState<string | null>(null)
  const data = access.data
  const failed = (error: unknown) => toast(t('adminForms.actionFailed', { message: errorMessage(error) }))
  const issue = () =>
    create.mutateAsync(undefined).then((r) => {
      setShown(r.token)
      toast(t(r.rotated ? 'admin.auth.scim.rotated' : 'admin.auth.scim.created'))
    }, failed)
  const copy = (value: string) =>
    navigator.clipboard?.writeText(value).then(
      () => toast(t('admin.auth.scim.copied')),
      () => undefined,
    )

  return (
    <Card>
      <CardHeader
        title={t('admin.auth.scim.title')}
        subtitle={t('admin.auth.scim.hint')}
        action={
          data && (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={data.enabled ? 'ghost' : 'primary'}
                disabled={create.isPending}
                onClick={issue}
              >
                {data.enabled ? <RotateCw size={14} /> : <KeyRound size={14} />}{' '}
                {t(data.enabled ? 'admin.auth.scim.rotate' : 'admin.auth.scim.create')}
              </Button>
              {data.enabled && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={revoke.isPending}
                  onClick={() =>
                    revoke.mutateAsync(undefined).then(() => {
                      setShown(null)
                      toast(t('admin.auth.scim.revoked'))
                    }, failed)
                  }
                >
                  <Trash2 size={14} /> {t('admin.auth.scim.revoke')}
                </Button>
              )}
            </div>
          )
        }
      />
      <CardBody className="space-y-3">
        {access.isLoading && <p className="text-sm text-muted">{t('common.loading')}</p>}
        {access.error && <Notice tone="critical">{errorMessage(access.error)}</Notice>}
        {data && (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted">{t('admin.auth.scim.baseUrl')}</dt>
            <dd className="flex items-center gap-2 font-mono text-xs">
              {data.baseUrl}
              <Button
                size="sm"
                variant="ghost"
                aria-label={t('admin.auth.scim.copy')}
                onClick={() => copy(data.baseUrl)}
              >
                <Copy size={14} />
              </Button>
            </dd>
            <dt className="text-muted">{t('admin.auth.scim.bearer')}</dt>
            <dd className="flex flex-wrap items-center gap-2">
              <Badge tone={data.enabled ? 'good' : 'neutral'}>
                {t(data.enabled ? 'admin.auth.scim.enabled' : 'admin.auth.scim.disabled')}
              </Badge>
              {data.enabled && data.hint && (
                <span className="font-mono text-xs">{t('admin.auth.scim.hintLabel', { hint: data.hint })}</span>
              )}
              {data.createdAt && (
                <span className="text-xs text-muted">
                  {t('admin.auth.scim.createdAt', { date: formatDateTime(data.createdAt) })}
                </span>
              )}
              {data.enabled && (
                <span className="text-xs text-muted">
                  {data.lastUsedAt
                    ? t('admin.auth.scim.lastUsed', { date: formatDateTime(data.lastUsedAt) })
                    : t('admin.auth.scim.neverUsed')}
                </span>
              )}
            </dd>
          </dl>
        )}
        {shown && (
          <div className="space-y-2">
            <Notice tone="warning">{t('admin.auth.scim.showOnce')}</Notice>
            <div className="flex items-center gap-2">
              <Input readOnly value={shown} className="font-mono text-xs" aria-label={t('admin.auth.scim.bearer')} />
              <Button size="sm" variant="ghost" onClick={() => copy(shown)}>
                <Copy size={14} /> {t('admin.auth.scim.copy')}
              </Button>
              <Button size="sm" onClick={() => setShown(null)}>
                {t('admin.auth.scim.done')}
              </Button>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
