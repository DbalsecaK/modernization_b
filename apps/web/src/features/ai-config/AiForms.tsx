import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useAddLocalModel,
  useAddPrice,
  useCreateConnection,
  useServedModels,
  useUpdateConnection,
  type Connection,
  type ConnectionProvider,
} from '@/api/ai'
import { Button, Field, Input, Select, Toggle } from '@/components/ui/primitives'
import { Drawer, toast } from '@/components/ui/overlay'
import { errorMessage } from '@/features/admin/AdminForms'
import { Notice } from '@/features/projects/NewProjectWizard'

/** A new connection (OpenRouter, or an openai-compatible server such as vLLM or Ollama with its base URL), or a
 * rename / key rotation of an existing one. The key is sent once to the API, which writes it to the secrets
 * store; it is never shown again. An openai-compatible server may have no key (ADR-0030). */
export function ConnectionForm({
  open,
  onClose,
  initial,
}: {
  open: boolean
  onClose: () => void
  initial?: Connection
}) {
  const { t } = useTranslation()
  const create = useCreateConnection()
  const update = useUpdateConnection()
  const [provider, setProvider] = useState<ConnectionProvider>(initial?.provider ?? 'openrouter')
  const [name, setName] = useState(initial?.name ?? '')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(initial?.baseUrl ?? '')
  const editing = !!initial
  const local = provider === 'openai-compatible'
  const busy = create.isPending || update.isPending
  const keyOk = apiKey === '' ? editing || local : apiKey.length >= 8
  const urlOk = !local || baseUrl.trim().length >= 8
  const valid = name.trim().length > 0 && keyOk && urlOk

  async function save() {
    try {
      if (initial) {
        await update.mutateAsync({
          id: initial.id,
          name: name.trim() !== initial.name ? name.trim() : undefined,
          apiKey: apiKey || undefined,
          baseUrl: local && baseUrl.trim() !== (initial.baseUrl ?? '') ? baseUrl.trim() : undefined,
        })
      } else {
        await create.mutateAsync({
          provider,
          name: name.trim(),
          apiKey: apiKey || undefined,
          baseUrl: local ? baseUrl.trim() : undefined,
        })
      }
      setApiKey('')
      toast(t('aiForms.connectionSaved', { name }))
      onClose()
    } catch (error) {
      toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={editing ? t('aiForms.editConnection') : t('ai.addConnection')}
      description={t('aiForms.connectionHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={!valid || busy} onClick={save}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <Field label={t('aiForms.provider')} hint={local ? t('aiForms.local.providerHint') : undefined}>
        <Select value={provider} disabled={editing} onChange={(e) => setProvider(e.target.value as ConnectionProvider)}>
          <option value="openrouter">{t('providers.openrouter')}</option>
          <option value="openai-compatible">{t('providers.openaiCompatible')}</option>
        </Select>
      </Field>
      <Field label={t('aiForms.connectionName')}>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={local ? 'Andes — vLLM' : 'Andes — OpenRouter'}
        />
      </Field>
      {local && (
        <Field label={t('aiForms.local.baseUrl')} hint={t('aiForms.local.baseUrlHint')}>
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="http://vllm.internal:8000/v1"
            autoComplete="off"
          />
        </Field>
      )}
      <Field
        label={editing ? t('aiForms.newApiKey') : local ? t('aiForms.local.apiKey') : t('aiForms.fields.apiKey')}
        hint={editing ? t('aiForms.rotateHint') : t('aiForms.secretHint')}
      >
        <Input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={local ? '' : 'sk-or-v1-…'}
          autoComplete="off"
        />
      </Field>
      <Notice tone="info">{t('aiForms.otherProviders')}</Notice>
    </Drawer>
  )
}

/** Add a model of an openai-compatible connection: typed by hand or picked from what the server lists, with the
 * price the tenant declares (zero by default, its own hardware). The model is visible only to this tenant. */
export function LocalModelForm({
  open,
  onClose,
  connection,
}: {
  open: boolean
  onClose: () => void
  connection: Connection
}) {
  const { t } = useTranslation()
  const add = useAddLocalModel()
  const [listing, setListing] = useState(false)
  const served = useServedModels(connection.id, open && listing)
  const [slug, setSlug] = useState('')
  const [contextWindow, setContextWindow] = useState('')
  const [inputPrice, setInputPrice] = useState('0')
  const [outputPrice, setOutputPrice] = useState('0')
  const [zdr, setZdr] = useState(false)
  const price = (v: string) => v.trim() !== '' && Number.isFinite(Number(v)) && Number(v) >= 0
  const valid = slug.trim().length > 0 && price(inputPrice) && price(outputPrice)

  async function save() {
    try {
      await add.mutateAsync({
        connectionId: connection.id,
        slug: slug.trim(),
        contextWindow: contextWindow ? Number(contextWindow) : null,
        zdr,
        inputPerMtok: inputPrice.trim(),
        outputPerMtok: outputPrice.trim(),
      })
      toast(t('aiForms.local.added', { model: slug.trim() }))
      setSlug('')
      setContextWindow('')
    } catch (error) {
      toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('aiForms.local.title', { name: connection.name })}
      description={t('aiForms.local.hint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={!valid || add.isPending} onClick={save}>
            {t('aiForms.local.add')}
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <Button size="sm" onClick={() => (listing ? void served.refetch() : setListing(true))}>
          {t('aiForms.local.listServed')}
        </Button>
        {served.isError && <Notice tone="warning">{t('aiForms.local.serverUnavailable')}</Notice>}
        {served.data?.length === 0 && <Notice tone="info">{t('aiForms.local.noServed')}</Notice>}
        {!!served.data?.length && (
          <Field label={t('aiForms.local.served')}>
            <Select
              value=""
              onChange={(e) => {
                const picked = served.data?.find((m) => m.slug === e.target.value)
                if (!picked) return
                setSlug(picked.slug)
                setContextWindow(picked.contextWindow ? String(picked.contextWindow) : '')
              }}
            >
              <option value="">{t('aiForms.local.pick')}</option>
              {served.data.map((m) => (
                <option key={m.slug} value={m.slug}>
                  {m.slug}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>
      <Field label={t('aiForms.local.slug')} hint={t('aiForms.local.slugHint')}>
        <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="meta-llama/Llama-3.1-8B-Instruct" />
      </Field>
      <Field label={t('aiForms.local.contextWindow')}>
        <Input
          type="number"
          min={1}
          value={contextWindow}
          onChange={(e) => setContextWindow(e.target.value)}
          placeholder="131072"
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('ai.inputPrice')}>
          <Input
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            value={inputPrice}
            onChange={(e) => setInputPrice(e.target.value)}
          />
        </Field>
        <Field label={t('ai.outputPrice')}>
          <Input
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            value={outputPrice}
            onChange={(e) => setOutputPrice(e.target.value)}
          />
        </Field>
      </div>
      <Toggle checked={zdr} onChange={setZdr} label={t('aiForms.local.zdr')} />
      <Notice tone="info">{t('aiForms.local.priceHint')}</Notice>
    </Drawer>
  )
}

const PRICE_FIELDS = [
  ['inputPerMtok', 'ai.inputPrice'],
  ['outputPerMtok', 'ai.outputPrice'],
  ['cacheReadPerMtok', 'ai.cacheReadPrice'],
  ['cacheWritePerMtok', 'aiForms.cacheWritePrice'],
  ['requestUsd', 'aiForms.requestPrice'],
] as const

type PriceKey = (typeof PRICE_FIELDS)[number][0]

/** A manual price version (superadministrator): applies from now on; past costs keep their price. */
export function ManualPriceForm({
  open,
  onClose,
  offeringId,
  offeringLabel,
}: {
  open: boolean
  onClose: () => void
  offeringId: string
  offeringLabel: string
}) {
  const { t } = useTranslation()
  const add = useAddPrice()
  const [values, setValues] = useState<Partial<Record<PriceKey, string>>>({})
  const valid = !!values.inputPerMtok && !!values.outputPerMtok

  async function save() {
    const optional = (key: PriceKey) => (values[key] ? values[key] : null)
    try {
      await add.mutateAsync({
        offeringId,
        inputPerMtok: values.inputPerMtok!,
        outputPerMtok: values.outputPerMtok!,
        cacheReadPerMtok: optional('cacheReadPerMtok'),
        cacheWritePerMtok: optional('cacheWritePerMtok'),
        requestUsd: optional('requestUsd'),
      })
      toast(t('aiForms.priceSaved'))
      onClose()
    } catch (error) {
      toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
    }
  }

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
          <Button variant="primary" disabled={!valid || add.isPending} onClick={save}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <Field label={t('ai.offering')}>
        <Input value={offeringLabel} readOnly />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        {PRICE_FIELDS.map(([key, label]) => (
          <Field key={key} label={t(label)}>
            <Input
              type="number"
              min="0"
              step="0.0001"
              inputMode="decimal"
              value={values[key] ?? ''}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            />
          </Field>
        ))}
      </div>
      <Notice tone="info">{t('ai.pricingHint')}</Notice>
    </Drawer>
  )
}
