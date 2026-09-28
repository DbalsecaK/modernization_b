import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Loader2, Plus, RefreshCw, XCircle } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { formatDateTime, formatUsd } from '@/lib/format'
import { agents, connections as seedConnections, offerings, profiles as seedProfiles } from '@/mocks/data'
import type { Effort, ModelProfile, ProviderConnection } from '@/mocks/types'
import { toast } from '@/components/ui/overlay'
import { ConnectionForm, PriceVersionForm } from './AiForms'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, PageHeader, Select, Table, Tabs, Td, Th, Toggle } from '@/components/ui/primitives'
import { agentName } from '@/features/catalog/AgentCard'
import { Notice } from '@/features/projects/NewProjectWizard'

const TABS = ['connections', 'catalog', 'profiles', 'assignment', 'pricing', 'policies', 'prompts', 'evaluations'] as const

export function AiConfigPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useTab(TABS, 'connections')
  return (
    <>
      <PageHeader title={t('ai.title')} description={t('ai.description')} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`ai.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {tab === 'connections' && <Connections />}
      {tab === 'catalog' && <Catalog />}
      {tab === 'profiles' && <Profiles />}
      {tab === 'assignment' && <Assignment />}
      {tab === 'pricing' && <Pricing />}
      {tab === 'policies' && <Policies />}
      {tab === 'prompts' && <Prompts />}
      {tab === 'evaluations' && <Evaluations />}
    </>
  )
}

// Shared across tabs so a connection added in one tab shows up in the others.
let connections: ProviderConnection[] = seedConnections
const profiles: ModelProfile[] = [...seedProfiles]

function connectionName(id: string) {
  return connections.find((c) => c.id === id)?.name ?? id
}

function Connections() {
  const { t } = useTranslation()
  const [testing, setTesting] = useState<string | null>(null)
  const [list, setList] = useState(connections)
  const [form, setForm] = useState<{ open: boolean; initial?: ProviderConnection }>({ open: false })
  const save = (c: ProviderConnection) => {
    const next = list.some((x) => x.id === c.id) ? list.map((x) => (x.id === c.id ? c : x)) : [...list, c]
    connections = next
    setList(next)
  }
  return (
    <div className="space-y-4">
      <ConnectionForm key={form.initial?.id ?? 'new'} open={form.open} initial={form.initial} onClose={() => setForm({ open: false })} onSave={save} />
      <div className="flex justify-end">
        <Button variant="primary" onClick={() => setForm({ open: true })}>
          <Plus size={16} /> {t('ai.addConnection')}
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((c) => (
          <Card key={c.id}>
            <CardBody className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-text">{c.name}</div>
                  <div className="text-xs text-muted">{t(`providers.${c.provider}`)}</div>
                </div>
                <Badge tone={c.status === 'connected' ? 'good' : c.status === 'error' ? 'critical' : 'neutral'}>
                  {c.status === 'connected' ? <CheckCircle2 size={12} /> : c.status === 'error' ? <XCircle size={12} /> : null}
                  {t(`ai.connectionStatus.${c.status}`)}
                </Badge>
              </div>
              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <dt className="text-muted">{t('ai.region')}</dt>
                  <dd className="text-text">{c.region}</dd>
                </div>
                <div>
                  <dt className="text-muted">{t('ai.models')}</dt>
                  <dd className="text-text">{c.models}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-muted">{t('ai.auth')}</dt>
                  <dd className="text-text">{c.auth}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-muted">{t('ai.lastCheck')}</dt>
                  <dd className="text-text">{formatDateTime(c.lastCheck)}</dd>
                </div>
              </dl>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={c.status === 'notConfigured' || testing === c.id}
                  onClick={() => {
                    setTesting(c.id)
                    window.setTimeout(() => setTesting(null), 1200)
                  }}
                >
                  {testing === c.id ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} {t('ai.testConnection')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setForm({ open: true, initial: c.status === 'notConfigured' ? { ...c, status: 'notConfigured' } : c })}>
                  {c.status === 'notConfigured' ? t('ai.configure') : t('common.edit')}
                </Button>
              </div>
            </CardBody>
          </Card>
        ))}
      </div>
      <Notice tone="info">{t('ai.credentialsNote')}</Notice>
    </div>
  )
}

function Catalog() {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader
        title={t('ai.catalogTitle')}
        subtitle={t('ai.catalogHint')}
        action={
          <Button size="sm">
            <RefreshCw size={14} /> {t('ai.sync')}
          </Button>
        }
      />
      <Table>
        <thead>
          <tr>
            <Th>{t('ai.family')}</Th>
            <Th>{t('ai.modelVersion')}</Th>
            <Th>{t('ai.offering')}</Th>
            <Th>{t('ai.context')}</Th>
            <Th>{t('ai.capabilities')}</Th>
            <Th>{t('ai.status')}</Th>
          </tr>
        </thead>
        <tbody>
          {offerings.map((o) => (
            <tr key={o.id}>
              <Td className="text-text">{o.family}</Td>
              <Td>
                <div className="text-text">{o.model}</div>
                <div className="text-xs text-muted">{t('ai.pinnedVersion', { version: o.version })}</div>
              </Td>
              <Td>
                <div className="text-xs text-text">{connectionName(o.connectionId)}</div>
                <div className="font-mono text-xs text-muted">{o.providerModelId}</div>
                <div className="text-xs text-muted">{o.region}</div>
              </Td>
              <Td className="tabular">{o.contextK}K</Td>
              <Td>
                <div className="flex flex-wrap gap-1">
                  {o.capabilities.map((c) => (
                    <Badge key={c}>{t(`capabilities.${c}`)}</Badge>
                  ))}
                </div>
              </Td>
              <Td>
                <Badge tone={o.status === 'available' ? 'good' : 'neutral'}>{t(`ai.offeringStatus.${o.status}`)}</Badge>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

const effortParam: Record<string, Record<Effort, string>> = {
  Claude: { low: 'effort = low', medium: 'effort = medium', high: 'effort = high', max: 'effort = max' },
  GPT: { low: 'reasoning_effort = low', medium: 'reasoning_effort = medium', high: 'reasoning_effort = high', max: 'reasoning_effort = high (+ max tokens)' },
}

function Profiles() {
  const { t } = useTranslation()
  const [list, setList] = useState(profiles)
  const [editing, setEditing] = useState(profiles[0].id)
  const profile = list.find((p) => p.id === editing)!
  const [profileName, setProfileName] = useState(profile.name)
  const [offeringId, setOfferingId] = useState(profile.offeringId)
  const [effort, setEffort] = useState<Effort>(profile.effort)
  const offering = offerings.find((o) => o.id === offeringId)!

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card>
        <CardHeader
          title={t('ai.profilesTitle')}
          action={
            <Button
              size="sm"
              onClick={() => {
                const id = `profile-${list.length + 1}`
                const created: ModelProfile = { id, name: t('aiForms.untitledProfile'), offeringId: offerings[0].id, effort: 'medium', providerParameter: 'effort = medium', maxOutputTokens: 16000 }
                profiles.push(created)
                setList([...profiles])
                setEditing(id)
                setOfferingId(created.offeringId)
                setEffort(created.effort)
                setProfileName(created.name)
              }}
            >
              <Plus size={14} /> {t('ai.newProfile')}
            </Button>
          }
        />
        <ul className="divide-y divide-border">
          {list.map((p) => {
            const o = offerings.find((x) => x.id === p.offeringId)!
            return (
              <li key={p.id}>
                <button
                  onClick={() => {
                    setEditing(p.id)
                    setProfileName(p.name)
                    setOfferingId(p.offeringId)
                    setEffort(p.effort)
                  }}
                  className={`w-full px-5 py-3 text-left hover:bg-surface-2 ${editing === p.id ? 'bg-surface-2' : ''}`}
                >
                  <div className="flex items-center gap-2 text-sm font-medium text-text">
                    {p.name}
                    <Badge className="ml-auto">{t(`effort.${p.effort}`)}</Badge>
                  </div>
                  <div className="text-xs text-muted">
                    {o.model} {o.version} · {connectionName(o.connectionId)}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      </Card>
      <Card>
        <CardHeader title={profileName} subtitle={t('ai.profileHint')} />
        <CardBody className="space-y-4">
          <Field label={t('aiForms.profileName')}>
            <Input value={profileName} onChange={(e) => setProfileName(e.target.value)} />
          </Field>
          <Field label={t('ai.offering')}>
            <Select value={offeringId} onChange={(e) => setOfferingId(e.target.value)}>
              {offerings.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.model} {o.version} — {connectionName(o.connectionId)} ({o.region})
                </option>
              ))}
            </Select>
          </Field>
          <div>
            <div className="mb-1.5 text-sm font-medium text-text">{t('ai.effort')}</div>
            <div className="grid grid-cols-4 gap-2">
              {(['low', 'medium', 'high', 'max'] as const).map((e) => (
                <button
                  key={e}
                  onClick={() => setEffort(e)}
                  aria-pressed={effort === e}
                  className={`rounded-md border px-3 py-2 text-sm ${effort === e ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-text-2 hover:bg-surface-2'}`}
                >
                  {t(`effort.${e}`)}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">
              {t('ai.providerParameter')}: <span className="font-mono text-text">{effortParam[offering.family]?.[effort] ?? '—'}</span>
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('ai.maxOutput')}>
              <Input type="number" defaultValue={profile.maxOutputTokens} />
            </Field>
            <Field label={t('ai.timeout')}>
              <Input type="number" defaultValue={600} />
            </Field>
          </div>
          <Field label={t('ai.fallback')} hint={t('ai.fallbackHint')}>
            <Select defaultValue={profile.fallbackOfferingId}>
              {offerings
                .filter((o) => o.id !== offeringId)
                .map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.model} {o.version} — {connectionName(o.connectionId)}
                  </option>
                ))}
            </Select>
          </Field>
          <Button
            variant="primary"
            onClick={() => {
              const updated = { ...profile, name: profileName, offeringId, effort, providerParameter: effortParam[offering.family]?.[effort] ?? profile.providerParameter }
              const i = profiles.findIndex((p) => p.id === profile.id)
              profiles[i] = updated
              setList([...profiles])
              toast(t('aiForms.profileSaved', { name: profileName }))
            }}
          >
            {t('common.save')}
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}

function Assignment() {
  const { t, i18n } = useTranslation()
  return (
    <div className="space-y-4">
      <Notice tone="info">{t('ai.cascade')}</Notice>
      <Card>
        <CardHeader title={t('ai.assignmentTitle')} subtitle={t('ai.assignmentHint')} />
        <Table>
          <thead>
            <tr>
              <Th>{t('wizard.agent')}</Th>
              <Th>{t('ai.phases')}</Th>
              <Th>{t('wizard.profile')}</Th>
              <Th>{t('ai.fallback')}</Th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => {
              const p = profiles.find((x) => x.id === a.defaultProfile)!
              const fb = offerings.find((o) => o.id === p.fallbackOfferingId)
              return (
                <tr key={a.id}>
                  <Td className="text-text">
                    {agentName(a, i18n.language)}
                    {a.mandatory && <Badge tone="brand" className="ml-2">{t('agents.mandatory')}</Badge>}
                  </Td>
                  <Td className="text-xs">{a.phases.map((ph) => t(`phases.${ph}`)).join(', ')}</Td>
                  <Td>
                    <Select defaultValue={p.id} className="h-9 min-w-48" aria-label={t('wizard.profile')}>
                      {profiles.map((x) => (
                        <option key={x.id} value={x.id}>
                          {x.name}
                        </option>
                      ))}
                    </Select>
                  </Td>
                  <Td className="text-xs">{fb ? `${fb.model} ${fb.version} — ${connectionName(fb.connectionId)}` : '—'}</Td>
                </tr>
              )
            })}
          </tbody>
        </Table>
      </Card>
    </div>
  )
}

function Pricing() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <PriceVersionForm open={open} onClose={() => setOpen(false)} />
      <CardHeader
        title={t('ai.pricingTitle')}
        subtitle={t('ai.pricingHint')}
        action={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus size={14} /> {t('ai.newPriceVersion')}
          </Button>
        }
      />
      <Table>
        <thead>
          <tr>
            <Th>{t('ai.offering')}</Th>
            <Th className="text-right">{t('ai.inputPrice')}</Th>
            <Th className="text-right">{t('ai.outputPrice')}</Th>
            <Th className="text-right">{t('ai.cacheReadPrice')}</Th>
            <Th>{t('ai.validFrom')}</Th>
          </tr>
        </thead>
        <tbody>
          {offerings.map((o) => (
            <tr key={o.id}>
              <Td>
                <div className="text-text">
                  {o.model} {o.version}
                </div>
                <div className="text-xs text-muted">{connectionName(o.connectionId)}</div>
              </Td>
              <Td className="text-right tabular">{formatUsd(o.inputPerMTokUsd, 2)}</Td>
              <Td className="text-right tabular">{formatUsd(o.outputPerMTokUsd, 2)}</Td>
              <Td className="text-right tabular">{formatUsd(o.inputPerMTokUsd / 10, 2)}</Td>
              <Td>{formatDateTime('2026-09-01T00:00:00Z')}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <CardBody>
        <p className="text-xs text-muted">{t('ai.pricingSample')}</p>
      </CardBody>
    </Card>
  )
}

function Policies() {
  const { t } = useTranslation()
  const [flags, setFlags] = useState({ bedrock: true, foundry: true, openai: false, local: false, differentVerifier: true, noTraining: true })
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title={t('ai.allowedProviders')} subtitle="Andes Bank" />
        <CardBody className="space-y-3">
          <Toggle checked={flags.bedrock} onChange={(v) => setFlags({ ...flags, bedrock: v })} label={`${t('providers.awsBedrock')} — us-east-1`} />
          <Toggle checked={flags.foundry} onChange={(v) => setFlags({ ...flags, foundry: v })} label={`${t('providers.azureFoundry')} — eastus2`} />
          <Toggle checked={flags.openai} onChange={(v) => setFlags({ ...flags, openai: v })} label={t('providers.openai')} />
          <Toggle checked={flags.local} onChange={(v) => setFlags({ ...flags, local: v })} label={t('ai.localModels')} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('ai.rules')} />
        <CardBody className="space-y-3">
          <Toggle checked={flags.differentVerifier} onChange={(v) => setFlags({ ...flags, differentVerifier: v })} label={t('ai.differentVerifier')} />
          <Toggle checked={flags.noTraining} onChange={(v) => setFlags({ ...flags, noTraining: v })} label={t('ai.noTraining')} />
          <Field label={t('ai.monthlyLimit')}>
            <Input type="number" defaultValue={10000} />
          </Field>
          <Field label={t('ai.retention')}>
            <Select defaultValue="30">
              <option value="0">{t('ai.retentionNone')}</option>
              <option value="30">{t('ai.retentionDays', { count: 30 })}</option>
              <option value="90">{t('ai.retentionDays', { count: 90 })}</option>
            </Select>
          </Field>
          <Button variant="primary" onClick={() => toast(t('aiForms.policiesSaved'))}>
            {t('common.save')}
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}

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
