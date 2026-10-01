import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Loader2, Plus, RefreshCw, Trash2, XCircle } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import {
  useCreateIntegration,
  useDeleteIntegration,
  useIntegrations,
  useTestIntegration,
  useUpdateIntegration,
  type Integration,
  type IntegrationKind,
} from '@/api/admin'
import { Badge, Button, Card, CardBody, EmptyState, Field, Input, Select } from '@/components/ui/primitives'
import { Drawer, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'
import { errorMessage } from './AdminForms'

const TONE = { ok: 'good', failed: 'critical', untested: 'neutral' } as const
// Figma (M7), Jira and Azure DevOps (M7b); Git arrives with the delivery milestone (the API refuses it until then).
const AVAILABLE: IntegrationKind[] = ['figma', 'jira', 'azure_devops']
const LATER: IntegrationKind[] = ['github', 'gitlab']
// Where each tool is (never a credential): the API checks the URLs are public https hosts.
const CONFIG: Record<string, string[]> = { figma: [], jira: ['site', 'email'], azure_devops: ['organization'] }
const PLACEHOLDER: Record<string, string> = {
  site: 'https://andesbank.atlassian.net',
  email: 'integraciones@andesbank.example',
  organization: 'https://dev.azure.com/andesbank',
}

/** A new integration of the tenant, or a rename / token rotation. The token is sent once and never shown again. */
function IntegrationForm({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: Integration }) {
  const { t } = useTranslation()
  const create = useCreateIntegration()
  const update = useUpdateIntegration()
  const [kind, setKind] = useState<IntegrationKind>(initial?.kind ?? 'figma')
  const [name, setName] = useState(initial?.name ?? '')
  const [token, setToken] = useState('')
  const [config, setConfig] = useState<Record<string, string>>(initial?.config ?? {})
  const fields = CONFIG[kind] ?? []
  const editing = !!initial
  const busy = create.isPending || update.isPending
  const valid =
    name.trim().length > 0 &&
    (editing ? token === '' || token.length >= 8 : token.length >= 8) &&
    (editing || fields.every((f) => (config[f] ?? '').trim().length > 0))

  async function save() {
    try {
      if (initial) {
        await update.mutateAsync({
          id: initial.id,
          name: name.trim() !== initial.name ? name.trim() : undefined,
          token: token || undefined,
        })
      } else {
        await create.mutateAsync({ kind, name: name.trim(), token, config })
      }
      setToken('')
      toast(t('integrations.saved', { name }))
      onClose()
    } catch (error) {
      toast(t('integrations.failed', { message: errorMessage(error) }))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={editing ? t('integrations.edit') : t('integrations.add')}
      description={t('integrations.formHint')}
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
      <Field label={t('integrations.kind')}>
        <Select value={kind} disabled={editing} onChange={(e) => setKind(e.target.value as IntegrationKind)}>
          {AVAILABLE.map((k) => (
            <option key={k} value={k}>
              {t(`integrations.kinds.${k}`)}
            </option>
          ))}
        </Select>
      </Field>
      {fields.map((f) => (
        <Field key={f} label={t(`integrations.config.${f}`)}>
          <Input
            value={config[f] ?? ''}
            disabled={editing}
            onChange={(e) => setConfig({ ...config, [f]: e.target.value })}
            placeholder={PLACEHOLDER[f]}
          />
        </Field>
      ))}
      <Field label={t('integrations.name')}>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Andes — Figma" />
      </Field>
      <Field
        label={editing ? t('integrations.newToken') : t('integrations.token')}
        hint={editing ? t('integrations.rotateHint') : t(`integrations.tokenHints.${kind}`)}
      >
        <Input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={kind === 'figma' ? 'figd_…' : '••••••••'}
          autoComplete="off"
        />
      </Field>
    </Drawer>
  )
}

/** Administration → Integrations: the external tools of the tenant, with their token in the secrets store. */
export function Integrations() {
  const { t } = useTranslation()
  const integrations = useIntegrations()
  const test = useTestIntegration()
  const remove = useDeleteIntegration()
  const [form, setForm] = useState<{ open: boolean; initial?: Integration; key: number }>({ open: false, key: 0 })
  const open = (initial?: Integration) => setForm((f) => ({ open: true, initial, key: f.key + 1 }))

  async function act(action: () => Promise<unknown>, ok: string) {
    try {
      await action()
      toast(ok)
    } catch (error) {
      toast(t('integrations.failed', { message: errorMessage(error) }))
    }
  }

  return (
    <div className="space-y-4">
      <IntegrationForm
        key={form.key}
        open={form.open}
        initial={form.initial}
        onClose={() => setForm((f) => ({ ...f, open: false }))}
      />
      <div className="flex justify-end">
        <Button variant="primary" onClick={() => open()}>
          <Plus size={16} /> {t('integrations.add')}
        </Button>
      </div>
      {integrations.data?.length === 0 && (
        <EmptyState title={t('integrations.none')} description={t('integrations.noneHint')} />
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(integrations.data ?? []).map((i) => {
          const testing = test.isPending && test.variables === i.id
          return (
            <Card key={i.id}>
              <CardBody className="space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-text">{i.name}</div>
                    <div className="text-xs text-muted">{t(`integrations.kinds.${i.kind}`)}</div>
                  </div>
                  <Badge tone={TONE[i.status]}>
                    {i.status === 'ok' ? (
                      <CheckCircle2 size={12} />
                    ) : i.status === 'failed' ? (
                      <XCircle size={12} />
                    ) : null}
                    {t(`integrations.status.${i.status}`)}
                  </Badge>
                </div>
                <dl className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <dt className="text-muted">{t('integrations.token')}</dt>
                    <dd className="text-text">{i.hasToken ? t('integrations.stored') : t('integrations.missing')}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t('integrations.account')}</dt>
                    <dd className="text-text">{i.account || '—'}</dd>
                  </div>
                  {Object.entries(i.config ?? {}).map(([k, v]) => (
                    <div key={k} className="col-span-2">
                      <dt className="text-muted">{t(`integrations.config.${k}`)}</dt>
                      <dd className="break-all text-text">{v}</dd>
                    </div>
                  ))}
                  <div className="col-span-2">
                    <dt className="text-muted">{t('integrations.lastCheck')}</dt>
                    <dd className="text-text">
                      {i.lastTestedAt ? formatDateTime(i.lastTestedAt) : '—'}
                      {i.lastTestDetail ? ` · ${i.lastTestDetail}` : ''}
                    </dd>
                  </div>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={testing}
                    onClick={() => act(() => test.mutateAsync(i.id), t('integrations.tested', { name: i.name }))}
                  >
                    {testing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}{' '}
                    {t('integrations.test')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => open(i)}>
                    {t('common.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('integrations.delete', { name: i.name })}
                    onClick={() => {
                      if (!window.confirm(t('integrations.confirmDelete', { name: i.name }))) return
                      void act(() => remove.mutateAsync(i.id), t('integrations.deleted', { name: i.name }))
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
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {LATER.map((k) => (
          <Card key={k}>
            <CardBody className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-text">{t(`integrations.kinds.${k}`)}</div>
                <div className="text-xs text-muted">{t('integrations.later')}</div>
              </div>
              <Badge tone="neutral">{t('integrations.soon')}</Badge>
            </CardBody>
          </Card>
        ))}
      </div>
      <Notice tone="info">{t('integrations.note')}</Notice>
    </div>
  )
}
