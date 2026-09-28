import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Loader2, Play, Plus, RefreshCw, Trash2, XCircle } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { formatCompact, formatDateTime, formatNumber, formatPrice, formatUsd } from '@/lib/format'
import { agents } from '@/mocks/data'
import { useMe } from '@/api/session'
import { useProjects } from '@/api/admin'
import {
  EFFORTS,
  resolveProfile,
  useAssignmentOptions,
  useAssignments,
  useCatalog,
  useConnections,
  useDeleteConnection,
  useDeleteProfile,
  useEffortMapping,
  useLoadOfferings,
  usePolicy,
  usePrices,
  useProfiles,
  useSaveProfile,
  useSetAssignment,
  useSetEffortMapping,
  useSetPolicy,
  useSyncCatalog,
  useTestConnection,
  useTestProfile,
  usd,
  type Assignment,
  type CatalogVersion,
  type Connection,
  type Effort,
  type Policy,
  type Profile,
  type ProfileTest,
} from '@/api/ai'
import { Textarea, toast } from '@/components/ui/overlay'
import { ConnectionForm, ManualPriceForm } from './AiForms'
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
import { agentName } from '@/features/catalog/AgentCard'
import { errorMessage } from '@/features/admin/AdminForms'
import { Notice } from '@/features/projects/NewProjectWizard'

const TABS = [
  'connections',
  'catalog',
  'profiles',
  'assignment',
  'pricing',
  'policies',
  'prompts',
  'evaluations',
] as const

export function AiConfigPage() {
  const { t } = useTranslation()
  const me = useMe()
  const [tab, setTab] = useTab(TABS, 'connections')
  return (
    <>
      <PageHeader title={t('ai.title')} description={t('ai.description')} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`ai.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {!me?.activeTenant ? (
        <Notice tone="info">{t('admin.noActiveTenant')}</Notice>
      ) : (
        <>
          {tab === 'connections' && <Connections />}
          {tab === 'catalog' && <Catalog />}
          {tab === 'profiles' && <Profiles />}
          {tab === 'assignment' && <AssignmentMatrix />}
          {tab === 'pricing' && <Pricing />}
          {tab === 'policies' && <Policies />}
          {tab === 'prompts' && <Prompts />}
          {tab === 'evaluations' && <Evaluations />}
        </>
      )}
    </>
  )
}

/** Runs a mutation with a toast on success or failure. */
async function run<T>(
  action: () => Promise<T>,
  ok: string | ((result: T) => string),
  fail: (message: string) => string,
) {
  try {
    const result = await action()
    toast(typeof ok === 'string' ? ok : ok(result))
  } catch (error) {
    toast(fail(errorMessage(error)))
  }
}

const CAPABILITY_KEYS: Record<string, string> = {
  tools: 'toolCalling',
  structured_output: 'structuredOutput',
  vision: 'vision',
  reasoning: 'reasoning',
}

/** The provider parameter of an effort; an empty object means the model takes none. */
const parameterText = (p: Record<string, unknown> | undefined) => (p && Object.keys(p).length ? JSON.stringify(p) : '')

function useIsSuperAdmin() {
  return !!useMe()?.platformRoles.includes('superAdmin')
}

function useRoleLabel() {
  const { i18n } = useTranslation()
  return (role: string) => {
    const agent = agents.find((a) => a.id === role)
    return agent ? agentName(agent, i18n.language) : role
  }
}

/** Offerings a profile can use: the ones loaded in the catalog, with the model they belong to. */
function useOfferedModels() {
  const catalog = useCatalog('', true)
  return useMemo(
    () =>
      (catalog.data ?? []).flatMap((v) =>
        v.offerings.map((o) => ({
          ...o,
          versionId: v.id,
          model: v.providerSlug,
          label: `${v.providerSlug} · ${o.upstreamProvider}`,
        })),
      ),
    [catalog.data],
  )
}

// ---------------------------------------------------------------------------------------------------------------
// Connections

const CONNECTION_TONE = { ok: 'good', failed: 'critical', untested: 'neutral' } as const

function Connections() {
  const { t } = useTranslation()
  const connections = useConnections()
  const test = useTestConnection()
  const remove = useDeleteConnection()
  const [form, setForm] = useState<{ open: boolean; initial?: Connection; key: number }>({ open: false, key: 0 })
  const open = (initial?: Connection) => setForm((f) => ({ open: true, initial, key: f.key + 1 }))

  return (
    <div className="space-y-4">
      <ConnectionForm
        key={form.key}
        open={form.open}
        initial={form.initial}
        onClose={() => setForm((f) => ({ ...f, open: false }))}
      />
      <div className="flex justify-end">
        <Button variant="primary" onClick={() => open()}>
          <Plus size={16} /> {t('ai.addConnection')}
        </Button>
      </div>
      {connections.data?.length === 0 && (
        <EmptyState title={t('ai.noConnections')} description={t('ai.noConnectionsHint')} />
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(connections.data ?? []).map((c) => {
          const testing = test.isPending && test.variables === c.id
          return (
            <Card key={c.id}>
              <CardBody className="space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-text">{c.name}</div>
                    <div className="text-xs text-muted">{t(`providers.${c.provider}`)}</div>
                  </div>
                  <Badge tone={CONNECTION_TONE[c.status]}>
                    {c.status === 'ok' ? (
                      <CheckCircle2 size={12} />
                    ) : c.status === 'failed' ? (
                      <XCircle size={12} />
                    ) : null}
                    {t(`ai.connectionStatus.${c.status}`)}
                  </Badge>
                </div>
                <dl className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <dt className="text-muted">{t('ai.credential')}</dt>
                    <dd className="text-text">
                      {c.hasCredential ? t('ai.credentialStored') : t('ai.credentialMissing')}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t('ai.lastCheck')}</dt>
                    <dd className="text-text">{c.lastTestedAt ? formatDateTime(c.lastTestedAt) : '—'}</dd>
                  </div>
                  {c.lastTestDetail && (
                    <div className="col-span-2">
                      <dt className="text-muted">{t('ai.lastResult')}</dt>
                      <dd className="text-text">{c.lastTestDetail}</dd>
                    </div>
                  )}
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={testing}
                    onClick={() =>
                      run(
                        () => test.mutateAsync(c.id),
                        t('ai.testDone', { name: c.name }),
                        (m) => t('aiForms.saveFailed', { message: m }),
                      )
                    }
                  >
                    {testing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}{' '}
                    {t('ai.testConnection')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => open(c)}>
                    {t('common.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('ai.deleteConnection', { name: c.name })}
                    onClick={() => {
                      if (!window.confirm(t('ai.confirmDeleteConnection', { name: c.name }))) return
                      void run(
                        () => remove.mutateAsync(c.id),
                        t('ai.connectionDeleted', { name: c.name }),
                        (m) => t('aiForms.saveFailed', { message: m }),
                      )
                    }}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </CardBody>
            </Card>
          )
        })}
      </div>
      <Notice tone="info">{t('ai.credentialsNote')}</Notice>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------------------------
// Catalog

const CATALOG_PAGE = 100

function Catalog() {
  const { t } = useTranslation()
  const [search, setSearch] = useState('')
  const [onlyOffered, setOnlyOffered] = useState(false)
  const catalog = useCatalog(search.trim(), onlyOffered)
  const sync = useSyncCatalog()
  const load = useLoadOfferings()
  const versions = catalog.data ?? []

  return (
    <Card>
      <CardHeader
        title={t('ai.catalogTitle')}
        subtitle={t('ai.catalogHint')}
        action={
          <Button
            size="sm"
            disabled={sync.isPending}
            onClick={() =>
              run(
                () => sync.mutateAsync(undefined),
                (r) => t('ai.syncDone', { versions: r.versions, families: r.families }),
                (m) => t('aiForms.saveFailed', { message: m }),
              )
            }
          >
            {sync.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} {t('ai.sync')}
          </Button>
        }
      />
      <CardBody className="flex flex-wrap items-end gap-4">
        <div className="w-full max-w-sm">
          <Field label={t('common.search')}>
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="claude, gpt-5, gemini…" />
          </Field>
        </div>
        <Toggle checked={onlyOffered} onChange={setOnlyOffered} label={t('ai.onlyOffered')} />
      </CardBody>
      {catalog.isSuccess && versions.length === 0 ? (
        <CardBody>
          <EmptyState title={t('ai.catalogEmpty')} description={t('ai.catalogEmptyHint')} />
        </CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('ai.family')}</Th>
              <Th>{t('ai.modelVersion')}</Th>
              <Th>{t('ai.context')}</Th>
              <Th>{t('ai.capabilities')}</Th>
              <Th>{t('ai.offerings')}</Th>
            </tr>
          </thead>
          <tbody>
            {versions.slice(0, CATALOG_PAGE).map((v) => (
              <CatalogRow
                key={v.id}
                version={v}
                loading={load.isPending && load.variables === v.id}
                onLoad={() =>
                  run(
                    () => load.mutateAsync(v.id),
                    (r) => t('ai.offeringsLoaded', { count: r.offerings, model: v.providerSlug }),
                    (m) => t('aiForms.saveFailed', { message: m }),
                  )
                }
              />
            ))}
          </tbody>
        </Table>
      )}
      {versions.length > CATALOG_PAGE && (
        <CardBody>
          <p className="text-xs text-muted">
            {t('ai.catalogTruncated', { shown: CATALOG_PAGE, total: versions.length })}
          </p>
        </CardBody>
      )}
    </Card>
  )
}

function CatalogRow({
  version: v,
  loading,
  onLoad,
}: {
  version: CatalogVersion
  loading: boolean
  onLoad: () => void
}) {
  const { t } = useTranslation()
  return (
    <tr>
      <Td className="text-text">{v.family}</Td>
      <Td>
        <div className="text-text">{v.name}</div>
        <div className="font-mono text-xs text-muted">{v.canonicalSlug}</div>
        {v.status === 'deprecated' && <Badge>{t('ai.offeringStatus.deprecated')}</Badge>}
      </Td>
      <Td className="tabular">{v.contextWindow ? formatCompact(v.contextWindow) : '—'}</Td>
      <Td>
        <div className="flex flex-wrap gap-1">
          {v.capabilities.map((c) => (
            <Badge key={c}>{CAPABILITY_KEYS[c] ? t(`capabilities.${CAPABILITY_KEYS[c]}`) : c}</Badge>
          ))}
        </div>
      </Td>
      <Td>
        <div className="space-y-1">
          {v.offerings.map((o) => (
            <div key={o.id} className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-mono text-text">{o.upstreamProvider}</span>
              {o.price && (
                <span className="tabular text-muted">
                  {formatPrice(usd(o.price.inputPerMtok)!)} / {formatPrice(usd(o.price.outputPerMtok)!)}
                </span>
              )}
              {o.zdr && <Badge tone="good">ZDR</Badge>}
              {o.status !== 'available' && <Badge>{t('ai.offeringStatus.unavailable')}</Badge>}
              {!o.allowedByPolicy && (
                <Badge tone="warning">
                  <span title={o.policyReason ?? undefined}>{t('ai.blockedByPolicy')}</span>
                </Badge>
              )}
            </div>
          ))}
          <Button size="sm" variant="ghost" disabled={loading} onClick={onLoad}>
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}{' '}
            {v.offerings.length ? t('ai.refreshOfferings') : t('ai.loadOfferings')}
          </Button>
        </div>
      </Td>
    </tr>
  )
}

// ---------------------------------------------------------------------------------------------------------------
// Profiles

function Profiles() {
  const { t } = useTranslation()
  const profiles = useProfiles()
  const [selected, setSelected] = useState<string | null>(null)
  const list = profiles.data ?? []
  const current = selected === 'new' ? null : (list.find((p) => p.id === selected) ?? list[0] ?? null)
  const editing = selected === 'new' || current !== null

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card>
        <CardHeader
          title={t('ai.profilesTitle')}
          action={
            <Button size="sm" onClick={() => setSelected('new')}>
              <Plus size={14} /> {t('ai.newProfile')}
            </Button>
          }
        />
        {list.length === 0 && profiles.isSuccess ? (
          <CardBody>
            <p className="text-sm text-muted">{t('ai.noProfiles')}</p>
          </CardBody>
        ) : (
          <ul className="divide-y divide-border">
            {list.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => setSelected(p.id)}
                  aria-current={current?.id === p.id}
                  className={`w-full px-5 py-3 text-left hover:bg-surface-2 ${current?.id === p.id && selected !== 'new' ? 'bg-surface-2' : ''}`}
                >
                  <div className="flex items-center gap-2 text-sm font-medium text-text">
                    {p.name}
                    <Badge className="ml-auto">{t(`effort.${p.effort}`)}</Badge>
                  </div>
                  <div className="text-xs text-muted">
                    {p.model} · {p.upstreamProvider}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {editing && (
        <ProfileEditor
          key={selected === 'new' ? 'new' : current?.id}
          profile={selected === 'new' ? null : current}
          profiles={list}
          onSaved={setSelected}
        />
      )}
    </div>
  )
}

function ProfileEditor({
  profile,
  profiles,
  onSaved,
}: {
  profile: Profile | null
  profiles: Profile[]
  onSaved: (id: string | null) => void
}) {
  const { t } = useTranslation()
  const connections = useConnections()
  const offered = useOfferedModels()
  const save = useSaveProfile()
  const remove = useDeleteProfile()
  const test = useTestProfile()
  const [result, setResult] = useState<ProfileTest | null>(null)
  const [name, setName] = useState(profile?.name ?? t('aiForms.untitledProfile'))
  const [connectionId, setConnectionId] = useState(profile?.connectionId ?? '')
  const [offeringId, setOfferingId] = useState(profile?.offeringId ?? '')
  const [effort, setEffort] = useState<Effort>(profile?.effort ?? 'medium')
  const [maxOutput, setMaxOutput] = useState(String(profile?.maxOutputTokens ?? 4096))
  const [temperature, setTemperature] = useState(profile?.temperature ?? '')
  const [timeout, setTimeoutSeconds] = useState(String(profile?.timeoutSeconds ?? 120))
  const [retries, setRetries] = useState(String(profile?.maxRetries ?? 2))
  const [fallback, setFallback] = useState(profile?.fallbackProfileId ?? '')
  const mapping = useEffortMapping(offeringId || null)
  const offering = offered.find((o) => o.id === offeringId)
  const connectionList = connections.data ?? []
  const valid = name.trim() && connectionId && offeringId && Number(maxOutput) > 0

  async function submit() {
    try {
      const saved = await save.mutateAsync({
        id: profile?.id ?? null,
        body: {
          name: name.trim(),
          connectionId,
          offeringId,
          effort,
          maxOutputTokens: Number(maxOutput),
          temperature: temperature === '' ? null : String(temperature),
          timeoutSeconds: Number(timeout),
          maxRetries: Number(retries),
          fallbackProfileId: fallback || null,
        },
      })
      toast(t('aiForms.profileSaved', { name: saved.name }))
      onSaved(saved.id)
    } catch (error) {
      toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
    }
  }

  return (
    <Card>
      <CardHeader title={name || t('aiForms.untitledProfile')} subtitle={t('ai.profileHint')} />
      <CardBody className="space-y-4">
        {connectionList.length === 0 && connections.isSuccess && (
          <Notice tone="warning">{t('ai.needConnection')}</Notice>
        )}
        {offered.length === 0 && <Notice tone="warning">{t('ai.needOfferings')}</Notice>}
        <Field label={t('aiForms.profileName')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('ai.connection')}>
            <Select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
              <option value="">{t('ai.choose')}</option>
              {connectionList.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('ai.offering')}>
            <Select value={offeringId} onChange={(e) => setOfferingId(e.target.value)}>
              <option value="">{t('ai.choose')}</option>
              {offered.map((o) => (
                <option key={o.id} value={o.id} disabled={!o.allowedByPolicy || o.status !== 'available'}>
                  {o.label}
                  {o.zdr ? ' · ZDR' : ''}
                  {!o.allowedByPolicy ? ` — ${t('ai.blockedByPolicy')}` : ''}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div>
          <div className="mb-1.5 text-sm font-medium text-text" id="effort-label">
            {t('ai.effort')}
          </div>
          <div className="grid grid-cols-4 gap-2" role="group" aria-labelledby="effort-label">
            {EFFORTS.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => setEffort(e)}
                aria-pressed={effort === e}
                className={`rounded-md border px-3 py-2 text-sm ${effort === e ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-text-2 hover:bg-surface-2'}`}
              >
                {t(`effort.${e}`)}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">
            {t('ai.providerParameter')}:{' '}
            <span className="font-mono text-text">
              {parameterText(mapping.data?.[effort]) || t('ai.noEffortParameter')}
            </span>
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t('ai.maxOutput')}
            hint={offering?.maxOutputTokens ? t('ai.maxAllowed', { count: offering.maxOutputTokens }) : undefined}
          >
            <Input type="number" min="1" value={maxOutput} onChange={(e) => setMaxOutput(e.target.value)} />
          </Field>
          <Field label={t('ai.temperature')} hint={t('ai.temperatureHint')}>
            <Input
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
            />
          </Field>
          <Field label={t('ai.timeout')}>
            <Input type="number" min="1" value={timeout} onChange={(e) => setTimeoutSeconds(e.target.value)} />
          </Field>
          <Field label={t('ai.retries')}>
            <Input type="number" min="0" max="10" value={retries} onChange={(e) => setRetries(e.target.value)} />
          </Field>
        </div>
        <Field label={t('ai.fallback')} hint={t('ai.fallbackHint')}>
          <Select value={fallback} onChange={(e) => setFallback(e.target.value)}>
            <option value="">{t('ai.noFallback')}</option>
            {profiles
              .filter((p) => p.id !== profile?.id)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {p.model} · {p.upstreamProvider}
                </option>
              ))}
          </Select>
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" disabled={!valid || save.isPending} onClick={submit}>
            {t('common.save')}
          </Button>
          {profile && (
            <>
              <Button
                disabled={test.isPending}
                onClick={async () => {
                  try {
                    setResult(await test.mutateAsync(profile.id))
                  } catch (error) {
                    toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
                  }
                }}
              >
                {test.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}{' '}
                {t('ai.testProfile')}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  if (!window.confirm(t('ai.confirmDeleteProfile', { name: profile.name }))) return
                  void run(
                    async () => {
                      await remove.mutateAsync(profile.id)
                      onSaved(null)
                    },
                    t('ai.profileDeleted', { name: profile.name }),
                    (m) => t('aiForms.saveFailed', { message: m }),
                  )
                }}
              >
                <Trash2 size={14} /> {t('common.remove')}
              </Button>
            </>
          )}
        </div>
        <p className="text-xs text-muted">{t('ai.testProfileHint')}</p>
        {result && <ProfileTestResult result={result} />}
      </CardBody>
    </Card>
  )
}

function ProfileTestResult({ result }: { result: ProfileTest }) {
  const { t } = useTranslation()
  if (!result.ok) return <Notice tone="critical">{t('ai.testFailed', { code: result.errorCode ?? '' })}</Notice>
  return (
    <Notice tone="good">
      <span>
        {t('ai.testOk', {
          input: formatNumber(result.inputTokens),
          output: formatNumber(result.outputTokens),
          cost: formatUsd(usd(result.costUsd) ?? 0, 6),
        })}
        {result.wasFallback && ` ${t('ai.usedFallback')}`} <span className="font-mono">“{result.content}”</span>
      </span>
    </Notice>
  )
}

// ---------------------------------------------------------------------------------------------------------------
// Assignment matrix: cascade Tenant → Project → Phase → Role (spec 12.4)

function AssignmentMatrix() {
  const { t } = useTranslation()
  const roleLabel = useRoleLabel()
  const options = useAssignmentOptions()
  const profiles = useProfiles()
  const projects = useProjects()
  const [projectId, setProjectId] = useState<string | null>(null)
  const assignments = useAssignments(projectId)
  const setAssignment = useSetAssignment()
  const phases = options.data?.phases ?? []
  const roles = options.data?.agentRoles ?? []
  const own = (assignments.data ?? []).filter((a) => a.projectId === projectId)
  const find = (phase: string | null, role: string | null) =>
    own.find((a) => a.phase === phase && a.agentRole === role)?.profileId ?? ''
  const combos = own.filter((a) => a.phase && a.agentRole)

  const assign = (phase: string | null, agentRole: string | null, profileId: string) =>
    run(
      () => setAssignment.mutateAsync({ projectId, phase, agentRole, profileId: profileId || null }),
      t('ai.assignmentSaved'),
      (m) => t('aiForms.saveFailed', { message: m }),
    )

  const profileSelect = (phase: string | null, role: string | null, label: string) => (
    <Select
      value={find(phase, role)}
      onChange={(e) => assign(phase, role, e.target.value)}
      className="h-9 min-w-56"
      aria-label={label}
    >
      <option value="">{t('ai.inherit')}</option>
      {(profiles.data ?? []).map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </Select>
  )

  return (
    <div className="space-y-4">
      <Notice tone="info">{t('ai.cascade')}</Notice>
      {profiles.isSuccess && profiles.data.length === 0 && <Notice tone="warning">{t('ai.needProfiles')}</Notice>}
      <Card>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label={t('ai.scope')}>
            <Select value={projectId ?? ''} onChange={(e) => setProjectId(e.target.value || null)}>
              <option value="">{t('ai.wholeTenant')}</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={projectId ? t('ai.projectDefault') : t('ai.tenantDefault')}>
            {profileSelect(null, null, projectId ? t('ai.projectDefault') : t('ai.tenantDefault'))}
          </Field>
        </CardBody>
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title={t('ai.byPhase')} subtitle={t('ai.byPhaseHint')} />
          <Table>
            <thead>
              <tr>
                <Th>{t('ai.phase')}</Th>
                <Th>{t('wizard.profile')}</Th>
              </tr>
            </thead>
            <tbody>
              {phases.map((ph) => (
                <tr key={ph}>
                  <Td className="text-text">{t(`phases.${ph}`)}</Td>
                  <Td>{profileSelect(ph, null, `${t('wizard.profile')} · ${t(`phases.${ph}`)}`)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card>
          <CardHeader title={t('ai.byRole')} subtitle={t('ai.byRoleHint')} />
          <Table>
            <thead>
              <tr>
                <Th>{t('wizard.agent')}</Th>
                <Th>{t('wizard.profile')}</Th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r}>
                  <Td className="text-text">{roleLabel(r)}</Td>
                  <Td>{profileSelect(null, r, `${t('wizard.profile')} · ${roleLabel(r)}`)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>
      <Combinations phases={phases} roles={roles} combos={combos} profiles={profiles.data ?? []} onAssign={assign} />
      <ResolveTester projectId={projectId} phases={phases} roles={roles} profiles={profiles.data ?? []} />
    </div>
  )
}

function Combinations({
  phases,
  roles,
  combos,
  profiles,
  onAssign,
}: {
  phases: string[]
  roles: string[]
  combos: Assignment[]
  profiles: Profile[]
  onAssign: (phase: string | null, role: string | null, profileId: string) => Promise<void>
}) {
  const { t } = useTranslation()
  const roleLabel = useRoleLabel()
  const [phase, setPhase] = useState('')
  const [role, setRole] = useState('')
  const [profileId, setProfileId] = useState('')
  const name = (id: string) => profiles.find((p) => p.id === id)?.name ?? id
  return (
    <Card>
      <CardHeader title={t('ai.combinations')} subtitle={t('ai.combinationsHint')} />
      <CardBody className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
        <Field label={t('ai.phase')}>
          <Select value={phase} onChange={(e) => setPhase(e.target.value)}>
            <option value="">{t('ai.choose')}</option>
            {phases.map((ph) => (
              <option key={ph} value={ph}>
                {t(`phases.${ph}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('wizard.agent')}>
          <Select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">{t('ai.choose')}</option>
            {roles.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('wizard.profile')}>
          <Select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
            <option value="">{t('ai.choose')}</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Button disabled={!phase || !role || !profileId} onClick={() => onAssign(phase, role, profileId)}>
          <Plus size={14} /> {t('ai.addCombination')}
        </Button>
      </CardBody>
      {combos.length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>{t('ai.phase')}</Th>
              <Th>{t('wizard.agent')}</Th>
              <Th>{t('wizard.profile')}</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {combos.map((a) => (
              <tr key={a.id}>
                <Td>{t(`phases.${a.phase}`)}</Td>
                <Td>{roleLabel(a.agentRole!)}</Td>
                <Td className="text-text">{name(a.profileId)}</Td>
                <Td className="text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('ai.removeCombination')}
                    onClick={() => onAssign(a.phase, a.agentRole, '')}
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
  )
}

function ResolveTester({
  projectId,
  phases,
  roles,
  profiles,
}: {
  projectId: string | null
  phases: string[]
  roles: string[]
  profiles: Profile[]
}) {
  const { t } = useTranslation()
  const roleLabel = useRoleLabel()
  const [phase, setPhase] = useState('')
  const [role, setRole] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  return (
    <Card>
      <CardHeader title={t('ai.resolveTitle')} subtitle={t('ai.resolveHint')} />
      <CardBody className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <Field label={t('ai.phase')}>
          <Select value={phase} onChange={(e) => setPhase(e.target.value)}>
            <option value="">{t('ai.any')}</option>
            {phases.map((ph) => (
              <option key={ph} value={ph}>
                {t(`phases.${ph}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('wizard.agent')}>
          <Select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">{t('ai.any')}</option>
            {roles.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </Select>
        </Field>
        <Button
          onClick={async () => {
            try {
              const r = await resolveProfile({
                projectId: projectId ?? undefined,
                phase: phase || undefined,
                agentRole: role || undefined,
              })
              setAnswer(
                r.profileId ? (profiles.find((p) => p.id === r.profileId)?.name ?? r.profileId) : t('ai.noProfile'),
              )
            } catch (error) {
              toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
            }
          }}
        >
          {t('ai.resolve')}
        </Button>
      </CardBody>
      {answer && (
        <CardBody>
          <p className="text-sm text-text" role="status">
            {t('ai.resolvedTo', { profile: answer })}
          </p>
        </CardBody>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------------------------------------------
// Pricing and effort table (global; edited by the superadministrator)

function Pricing() {
  const { t } = useTranslation()
  const isSuperAdmin = useIsSuperAdmin()
  const offered = useOfferedModels()
  const [chosen, setChosen] = useState('')
  const offeringId = chosen || offered[0]?.id || ''
  const offering = offered.find((o) => o.id === offeringId)
  const prices = usePrices(offeringId || null)
  const [form, setForm] = useState({ open: false, key: 0 })

  if (offered.length === 0) {
    return <EmptyState title={t('ai.needOfferings')} description={t('ai.catalogEmptyHint')} />
  }
  return (
    <div className="space-y-6">
      <Card>
        <CardBody className="max-w-xl">
          <Field label={t('ai.offering')}>
            <Select value={offeringId} onChange={(e) => setChosen(e.target.value)}>
              {offered.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
        </CardBody>
      </Card>
      <Card>
        {offering && (
          <ManualPriceForm
            key={form.key}
            open={form.open}
            onClose={() => setForm((f) => ({ ...f, open: false }))}
            offeringId={offering.id}
            offeringLabel={offering.label}
          />
        )}
        <CardHeader
          title={t('ai.pricingTitle')}
          subtitle={t('ai.pricingHint')}
          action={
            isSuperAdmin && (
              <Button size="sm" onClick={() => setForm((f) => ({ open: true, key: f.key + 1 }))}>
                <Plus size={14} /> {t('ai.newPriceVersion')}
              </Button>
            )
          }
        />
        <Table>
          <thead>
            <tr>
              <Th>{t('ai.validFrom')}</Th>
              <Th>{t('ai.validTo')}</Th>
              <Th className="text-right">{t('ai.inputPrice')}</Th>
              <Th className="text-right">{t('ai.outputPrice')}</Th>
              <Th className="text-right">{t('ai.cacheReadPrice')}</Th>
              <Th className="text-right">{t('aiForms.cacheWritePrice')}</Th>
              <Th>{t('ai.priceSource')}</Th>
            </tr>
          </thead>
          <tbody>
            {(prices.data ?? []).map((p) => (
              <tr key={p.id}>
                <Td>{formatDateTime(p.validFrom)}</Td>
                <Td>{p.validTo ? formatDateTime(p.validTo) : <Badge tone="good">{t('ai.current')}</Badge>}</Td>
                <Td className="text-right tabular">{formatPrice(usd(p.inputPerMtok))}</Td>
                <Td className="text-right tabular">{formatPrice(usd(p.outputPerMtok))}</Td>
                <Td className="text-right tabular">{formatPrice(usd(p.cacheReadPerMtok))}</Td>
                <Td className="text-right tabular">{formatPrice(usd(p.cacheWritePerMtok))}</Td>
                <Td>
                  <Badge>{t(`ai.priceSources.${p.source}`)}</Badge>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {offering && <EffortTable key={offering.id} offeringId={offering.id} editable={isSuperAdmin} />}
    </div>
  )
}

function EffortTable({ offeringId, editable }: { offeringId: string; editable: boolean }) {
  const { t } = useTranslation()
  const mapping = useEffortMapping(offeringId)
  const setMapping = useSetEffortMapping()
  const [drafts, setDrafts] = useState<Partial<Record<Effort, string>>>({})
  const text = (e: Effort) => drafts[e] ?? parameterText(mapping.data?.[e])

  async function save() {
    try {
      const parameters: Partial<Record<Effort, Record<string, unknown>>> = {}
      for (const e of EFFORTS) {
        const value = text(e).trim()
        if (value) parameters[e] = JSON.parse(value) as Record<string, unknown>
      }
      await setMapping.mutateAsync({ offeringId, parameters })
      setDrafts({})
      toast(t('ai.effortSaved'))
    } catch (error) {
      toast(
        t('aiForms.saveFailed', { message: error instanceof SyntaxError ? t('ai.invalidJson') : errorMessage(error) }),
      )
    }
  }

  return (
    <Card>
      <CardHeader title={t('ai.effortTitle')} subtitle={t('ai.effortHint')} />
      <CardBody className="space-y-3">
        {EFFORTS.map((e) => (
          <Field key={e} label={t(`effort.${e}`)}>
            {editable ? (
              <Textarea
                rows={1}
                className="font-mono text-xs"
                value={text(e)}
                onChange={(ev) => setDrafts({ ...drafts, [e]: ev.target.value })}
              />
            ) : (
              <p className="font-mono text-xs text-text">{text(e) || t('ai.noEffortParameter')}</p>
            )}
          </Field>
        ))}
        {editable && (
          <Button variant="primary" disabled={setMapping.isPending} onClick={save}>
            {t('common.save')}
          </Button>
        )}
      </CardBody>
    </Card>
  )
}

// ---------------------------------------------------------------------------------------------------------------
// Policies of the tenant (spec 12.6)

function Policies() {
  const policy = usePolicy()
  return policy.data ? <PolicyForm initial={policy.data} /> : null
}

const list = (value: string) =>
  value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

function PolicyForm({ initial }: { initial: Policy }) {
  const { t } = useTranslation()
  const setPolicy = useSetPolicy()
  const [openrouter, setOpenrouter] = useState(initial.openrouterAllowed)
  const [zdr, setZdr] = useState(initial.requireZdr)
  const [noTraining, setNoTraining] = useState(initial.denyDataCollection)
  const [allowed, setAllowed] = useState((initial.allowedUpstreamProviders ?? []).join(', '))
  const [denied, setDenied] = useState(initial.deniedUpstreamProviders.join(', '))
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title={t('ai.allowedProviders')} subtitle={t('ai.allowedProvidersHint')} />
        <CardBody className="space-y-4">
          <Toggle checked={openrouter} onChange={setOpenrouter} label={t('ai.openrouterAllowed')} />
          <Field label={t('ai.allowedUpstream')} hint={t('ai.allowedUpstreamHint')}>
            <Input
              value={allowed}
              onChange={(e) => setAllowed(e.target.value)}
              placeholder="anthropic, openai, azure"
            />
          </Field>
          <Field label={t('ai.deniedUpstream')} hint={t('ai.deniedUpstreamHint')}>
            <Input value={denied} onChange={(e) => setDenied(e.target.value)} placeholder="deepinfra" />
          </Field>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('ai.rules')} />
        <CardBody className="space-y-4">
          <Toggle checked={zdr} onChange={setZdr} label={t('ai.requireZdr')} />
          <Toggle checked={noTraining} onChange={setNoTraining} label={t('ai.noTraining')} />
          <Button
            variant="primary"
            disabled={setPolicy.isPending}
            onClick={() =>
              run(
                () =>
                  setPolicy.mutateAsync({
                    openrouterAllowed: openrouter,
                    requireZdr: zdr,
                    denyDataCollection: noTraining,
                    allowedUpstreamProviders: list(allowed).length ? list(allowed) : null,
                    deniedUpstreamProviders: list(denied),
                  }),
                t('aiForms.policiesSaved'),
                (m) => t('aiForms.saveFailed', { message: m }),
              )
            }
          >
            {t('common.save')}
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------------------------
// Prompts and evaluations arrive with the agents (M3); these tabs keep the prototype content.

function Prompts() {
  const { t } = useTranslation()
  const items = [
    ['rules-extractor / system', '2.1.0', '2026-09-10'],
    ['rules-verifier / system', '1.3.0', '2026-09-02'],
    ['backend-dev / system', '1.5.0', '2026-08-28'],
    ['Andes Bank constitution', '1.0.0', '2026-08-15'],
  ]
  return (
    <Card>
      <CardHeader title={t('ai.promptsTitle')} subtitle={t('ai.promptsHint')} />
      <Table>
        <thead>
          <tr>
            <Th>{t('ai.prompt')}</Th>
            <Th>{t('ai.version')}</Th>
            <Th>{t('ai.published')}</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {items.map(([name, version, date]) => (
            <tr key={name}>
              <Td className="font-mono text-xs text-text">{name}</Td>
              <Td>{version}</Td>
              <Td>{formatDateTime(`${date}T12:00:00Z`)}</Td>
              <Td className="text-right">
                <Button size="sm" variant="ghost">
                  {t('ai.history')}
                </Button>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function Evaluations() {
  const { t } = useTranslation()
  const rows = [
    ['Sybase SP (reference)', 'Deep analysis', 94, 2, 3],
    ['Sybase SP (reference)', 'Maximum reasoning', 97, 1, 1],
    ['CICS + BMS (reference)', 'Deep analysis', 88, 4, 6],
    ['ASPX (reference)', 'Deep analysis', 81, 5, 9],
  ] as const
  return (
    <Card>
      <CardHeader title={t('ai.evaluationsTitle')} subtitle={t('ai.evaluationsHint')} />
      <Table>
        <thead>
          <tr>
            <Th>{t('ai.referenceApp')}</Th>
            <Th>{t('wizard.profile')}</Th>
            <Th className="text-right">{t('ai.recall')}</Th>
            <Th className="text-right">{t('ai.hallucinations')}</Th>
            <Th className="text-right">{t('ai.precisionErrors')}</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([app, profile, recall, hall, prec]) => (
            <tr key={app + profile}>
              <Td className="text-text">{app}</Td>
              <Td>{profile}</Td>
              <Td className="text-right tabular">{recall}%</Td>
              <Td className="text-right tabular">{hall}</Td>
              <Td className="text-right tabular">{prec}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}
