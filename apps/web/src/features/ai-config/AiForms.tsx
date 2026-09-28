import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Loader2, RefreshCw } from 'lucide-react'
import type { ModelOffering, ProviderConnection } from '@/mocks/types'
import { offerings } from '@/mocks/data'
import { Badge, Button, Field, Input, Select, Toggle } from '@/components/ui/primitives'
import { CheckboxGroup, Drawer, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'

type Provider = ProviderConnection['provider']

// Fields each provider needs. Secrets are written to the vault and never read back.
const providerFields: Record<Provider, { key: string; secret?: boolean; placeholder: string }[]> = {
  azureFoundry: [
    { key: 'endpoint', placeholder: 'https://<resource>.services.ai.azure.com' },
    { key: 'tenantId', placeholder: '00000000-0000-0000-0000-000000000000' },
    { key: 'clientId', placeholder: '00000000-0000-0000-0000-000000000000' },
    { key: 'clientSecret', secret: true, placeholder: '••••••••' },
  ],
  awsBedrock: [
    { key: 'roleArn', placeholder: 'arn:aws:iam::123456789012:role/nexti-bedrock' },
    { key: 'externalId', placeholder: 'nexti-andes-7f3a' },
  ],
  openai: [
    { key: 'apiKey', secret: true, placeholder: 'sk-…' },
    { key: 'organization', placeholder: 'org-…' },
  ],
  anthropic: [{ key: 'apiKey', secret: true, placeholder: 'sk-ant-…' }],
  vertex: [
    { key: 'projectId', placeholder: 'andes-ai-prod' },
    { key: 'serviceAccount', secret: true, placeholder: 'service-account.json' },
  ],
}

const regions: Record<Provider, string[]> = {
  azureFoundry: ['eastus2', 'westeurope', 'brazilsouth'],
  awsBedrock: ['us-east-1', 'us-west-2', 'sa-east-1'],
  openai: ['global'],
  anthropic: ['global'],
  vertex: ['us-central1', 'southamerica-east1'],
}

const authMethod: Record<Provider, string> = {
  azureFoundry: 'Entra ID service principal',
  awsBedrock: 'IAM role (cross-account)',
  openai: 'API key (Vault)',
  anthropic: 'API key (Vault)',
  vertex: 'Service account (Vault)',
}

export function ConnectionForm({
  open,
  onClose,
  onSave,
  initial,
}: {
  open: boolean
  onClose: () => void
  onSave: (c: ProviderConnection) => void
  initial?: ProviderConnection
}) {
  const { t } = useTranslation()
  const [provider, setProvider] = useState<Provider>(initial?.provider ?? 'azureFoundry')
  const [name, setName] = useState(initial?.name ?? '')
  const [region, setRegion] = useState(initial?.region ?? regions.azureFoundry[0])
  const [values, setValues] = useState<Record<string, string>>({})
  const [test, setTest] = useState<'idle' | 'running' | 'ok'>(initial?.status === 'connected' ? 'ok' : 'idle')
  const [selected, setSelected] = useState<string[]>([])
  const discovered: ModelOffering[] = offerings.filter((o) => (provider === 'openai' ? o.connectionId === 'c3' : provider === 'awsBedrock' ? o.connectionId === 'c2' : o.connectionId === 'c1'))
  const editing = !!initial

  function runTest() {
    setTest('running')
    window.setTimeout(() => {
      setTest('ok')
      setSelected(discovered.map((o) => o.id))
    }, 1100)
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={editing ? t('aiForms.editConnection') : t('ai.addConnection')}
      description={t('aiForms.connectionHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim() || test !== 'ok'}
            onClick={() => {
              onSave({
                id: initial?.id ?? `c${Date.now()}`,
                provider,
                name,
                region,
                auth: authMethod[provider],
                status: 'connected',
                models: selected.length || initial?.models || 0,
                lastCheck: new Date().toISOString(),
              })
              toast(t('aiForms.connectionSaved', { name }))
              onClose()
            }}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <Field label={t('aiForms.provider')}>
        <Select
          value={provider}
          disabled={editing}
          onChange={(e) => {
            const p = e.target.value as Provider
            setProvider(p)
            setRegion(regions[p][0])
            setTest('idle')
            setValues({})
          }}
        >
          {(Object.keys(providerFields) as Provider[]).map((p) => (
            <option key={p} value={p}>
              {t(`providers.${p}`)}
            </option>
          ))}
        </Select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('aiForms.connectionName')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Andes — Azure AI Foundry" />
        </Field>
        <Field label={t('ai.region')}>
          <Select value={region} onChange={(e) => setRegion(e.target.value)}>
            {regions[provider].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {providerFields[provider].map((f) => (
          <Field key={f.key} label={t(`aiForms.fields.${f.key}`)} hint={f.secret ? t('aiForms.secretHint') : undefined}>
            <Input
              type={f.secret ? 'password' : 'text'}
              value={values[f.key] ?? ''}
              onChange={(e) => {
                setValues({ ...values, [f.key]: e.target.value })
                setTest('idle')
              }}
              placeholder={f.placeholder}
              autoComplete="off"
            />
          </Field>
        ))}
      </div>
      {provider === 'awsBedrock' && <Notice tone="info">{t('aiForms.bedrockHint')}</Notice>}
      {provider === 'azureFoundry' && <Notice tone="info">{t('aiForms.foundryHint')}</Notice>}
      <div className="flex items-center gap-3">
        <Button onClick={runTest} disabled={test === 'running'}>
          {test === 'running' ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} {t('ai.testConnection')}
        </Button>
        {test === 'ok' && (
          <span className="flex items-center gap-1.5 text-sm text-good-ink">
            <CheckCircle2 size={16} /> {t('aiForms.testOk', { count: discovered.length })}
          </span>
        )}
      </div>
      {test === 'ok' && (
        <Field label={t('aiForms.discovered')} hint={t('aiForms.discoveredHint')}>
          <CheckboxGroup
            columns={1}
            options={discovered.map((o) => ({
              id: o.id,
              label: (
                <span className="flex w-full items-center justify-between gap-2">
                  <span>
                    {o.model} {o.version} <span className="font-mono text-xs text-muted">{o.providerModelId}</span>
                  </span>
                  <Badge>{o.contextK}K</Badge>
                </span>
              ),
            }))}
            value={selected}
            onChange={setSelected}
          />
        </Field>
      )}
    </Drawer>
  )
}

export function PriceVersionForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [offering, setOffering] = useState(offerings[0].id)
  const [from, setFrom] = useState('2026-10-01')
  const [batch, setBatch] = useState(false)
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('ai.newPriceVersion')}
      description={t('aiForms.priceHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              toast(t('aiForms.priceSaved'))
              onClose()
            }}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <Field label={t('ai.offering')}>
        <Select value={offering} onChange={(e) => setOffering(e.target.value)}>
          {offerings.map((o) => (
            <option key={o.id} value={o.id}>
              {o.model} {o.version} — {o.providerModelId}
            </option>
          ))}
        </Select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('ai.inputPrice')}>
          <Input type="number" step="0.01" defaultValue={offerings.find((o) => o.id === offering)?.inputPerMTokUsd} />
        </Field>
        <Field label={t('ai.outputPrice')}>
          <Input type="number" step="0.01" defaultValue={offerings.find((o) => o.id === offering)?.outputPerMTokUsd} />
        </Field>
        <Field label={t('ai.cacheReadPrice')}>
          <Input type="number" step="0.01" />
        </Field>
        <Field label={t('aiForms.cacheWritePrice')}>
          <Input type="number" step="0.01" />
        </Field>
      </div>
      <Field label={t('ai.validFrom')}>
        <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
      </Field>
      <Toggle checked={batch} onChange={setBatch} label={t('aiForms.batchDiscount')} />
      <Notice tone="info">{t('ai.pricingHint')}</Notice>
    </Drawer>
  )
}
