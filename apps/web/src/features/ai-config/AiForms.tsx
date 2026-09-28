import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAddPrice, useCreateConnection, useUpdateConnection, type Connection } from '@/api/ai'
import { Button, Field, Input, Select } from '@/components/ui/primitives'
import { Drawer, toast } from '@/components/ui/overlay'
import { errorMessage } from '@/features/admin/AdminForms'
import { Notice } from '@/features/projects/NewProjectWizard'

/** A new OpenRouter connection, or a rename / key rotation of an existing one. The key is sent once to the API,
 * which writes it to the secrets store; it is never shown again. */
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
  const [name, setName] = useState(initial?.name ?? '')
  const [apiKey, setApiKey] = useState('')
  const editing = !!initial
  const busy = create.isPending || update.isPending
  const valid = name.trim().length > 0 && (editing ? apiKey === '' || apiKey.length >= 8 : apiKey.length >= 8)

  async function save() {
    try {
      if (initial) {
        await update.mutateAsync({
          id: initial.id,
          name: name.trim() !== initial.name ? name.trim() : undefined,
          apiKey: apiKey || undefined,
        })
      } else {
        await create.mutateAsync({ provider: 'openrouter', name: name.trim(), apiKey })
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
      <Field label={t('aiForms.provider')}>
        <Select value="openrouter" disabled>
          <option value="openrouter">{t('providers.openrouter')}</option>
        </Select>
      </Field>
      <Field label={t('aiForms.connectionName')}>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Andes — OpenRouter" />
      </Field>
      <Field
        label={editing ? t('aiForms.newApiKey') : t('aiForms.fields.apiKey')}
        hint={editing ? t('aiForms.rotateHint') : t('aiForms.secretHint')}
      >
        <Input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-or-v1-…"
          autoComplete="off"
        />
      </Field>
      <Notice tone="info">{t('aiForms.otherProviders')}</Notice>
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
