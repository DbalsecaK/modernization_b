import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import {
  draftAdapter,
  tryAdapter,
  useCreateAdapter,
  useDeleteAdapter,
  useTenantAdapters,
  type AdapterSpec,
  type TryResult,
} from '@/api/adapters'
import { Badge, Button, Field, Input, Table, Td, Th } from '@/components/ui/primitives'
import { Drawer, Textarea, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'

// The adapter studio (ADR-0039): describe a technology, let a model draft the declaration, try it on samples, keep
// it as an experimental adapter. The declaration is data: the platform runs its patterns, never code of a model.
const EMPTY_SPEC = `{
  "key": "my-language",
  "name": "My language",
  "extensions": [".src"],
  "comment_prefixes": ["--"],
  "unit": "^\\\\s*PROCEDURE\\\\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
  "parameter": null,
  "call": "\\\\bCALL\\\\s+(?P<callee>[A-Za-z_][A-Za-z0-9_]*)",
  "reads": ["\\\\bFROM\\\\s+(?P<table>[A-Za-z_][A-Za-z0-9_.]*)"],
  "writes": ["\\\\bUPDATE\\\\s+(?P<table>[A-Za-z_][A-Za-z0-9_.]*)", "\\\\bINSERT\\\\s+INTO\\\\s+(?P<table>[A-Za-z_][A-Za-z0-9_.]*)"],
  "infrastructure_keywords": ["LOG", "COMMIT", "ROLLBACK"],
  "control_keywords": ["IF", "ELSE", "WHILE", "RETURN"],
  "type_map": {"INT": "integer(32,signed)"}
}`

function message(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error)
}

export function TenantAdapters() {
  const { t } = useTranslation()
  const adapters = useTenantAdapters()
  const remove = useDeleteAdapter()
  const [open, setOpen] = useState(false)
  const [opened, setOpened] = useState(0)
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-text">{t('catalog.studio.title')}</div>
          <div className="text-xs text-muted">{t('catalog.studio.hint')}</div>
        </div>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setOpened((n) => n + 1)
            setOpen(true)
          }}
        >
          {t('catalog.studio.create')}
        </Button>
      </div>
      <StudioDrawer key={opened} open={open} onClose={() => setOpen(false)} />
      {(adapters.data ?? []).length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>{t('catalog.adapter')}</Th>
              <Th>{t('catalog.level')}</Th>
              <Th>{t('catalog.studio.extensions')}</Th>
              <Th className="text-right" />
            </tr>
          </thead>
          <tbody>
            {(adapters.data ?? []).map((a) => (
              <tr key={a.id}>
                <Td className="text-text">
                  {a.name}
                  <div className="font-mono text-xs text-muted">{a.key}</div>
                </Td>
                <Td>
                  <Badge tone="neutral">{t('catalog.studio.experimental')}</Badge>
                </Td>
                <Td className="font-mono text-xs">{((a.spec.extensions as string[]) ?? []).join(', ')}</Td>
                <Td className="text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`${t('catalog.studio.delete')} ${a.name}`}
                    disabled={remove.isPending}
                    onClick={() => {
                      if (window.confirm(t('catalog.studio.confirmDelete', { name: a.name })))
                        remove.mutate(a.id, { onError: (e) => toast(message(e)) })
                    }}
                  >
                    <Trash2 size={14} />
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  )
}

function StudioDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateAdapter()
  const [description, setDescription] = useState('')
  const [key, setKey] = useState('')
  const [samplePath, setSamplePath] = useState('sample.src')
  const [sample, setSample] = useState('')
  const [specText, setSpecText] = useState(EMPTY_SPEC)
  const [result, setResult] = useState<TryResult | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [busy, setBusy] = useState<'draft' | 'try' | null>(null)

  const parsedSpec = (): AdapterSpec | null => {
    try {
      return JSON.parse(specText) as AdapterSpec
    } catch {
      setProblems([t('catalog.studio.invalidJson')])
      return null
    }
  }
  const samples = () => (sample.trim() ? [{ path: samplePath || 'sample.src', text: sample }] : [])

  async function draft() {
    if (!samples().length) return setProblems([t('catalog.studio.needSample')])
    setBusy('draft')
    setProblems([])
    try {
      const found = await draftAdapter(
        description || t('catalog.studio.defaultDescription'),
        samples(),
        key || undefined,
      )
      if (found.spec) setSpecText(JSON.stringify(found.spec, null, 2))
      if (found.summary) setResult({ summary: found.summary, digest: '' })
      setProblems(found.problems)
    } catch (e) {
      setProblems([message(e)])
    } finally {
      setBusy(null)
    }
  }

  async function tryIt() {
    const spec = parsedSpec()
    if (!spec) return
    if (!samples().length) return setProblems([t('catalog.studio.needSample')])
    setBusy('try')
    setProblems([])
    try {
      setResult(await tryAdapter(spec, samples()))
    } catch (e) {
      setProblems([message(e)])
    } finally {
      setBusy(null)
    }
  }

  async function save() {
    const spec = parsedSpec()
    if (!spec) return
    try {
      const created = await create.mutateAsync(spec)
      toast(t('catalog.studio.saved', { name: created.name }))
      onClose()
    } catch (e) {
      setProblems([message(e)])
    }
  }

  const metrics = (result?.summary.metrics ?? {}) as Record<string, number>
  const classification = (result?.summary.classification ?? {}) as Record<string, number>
  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={t('catalog.studio.create')}
      description={t('catalog.studio.drawerHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={create.isPending || !result} onClick={() => void save()}>
            {t('catalog.studio.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('catalog.studio.description')}>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label={t('catalog.studio.key')} hint={t('catalog.studio.keyHint')}>
          <Input value={key} onChange={(e) => setKey(e.target.value)} placeholder="rpg-iv" />
        </Field>
      </div>
      <Field label={t('catalog.studio.samplePath')}>
        <Input value={samplePath} onChange={(e) => setSamplePath(e.target.value)} />
      </Field>
      <Field label={t('catalog.studio.sample')} hint={t('catalog.studio.sampleHint')}>
        <Textarea value={sample} onChange={(e) => setSample(e.target.value)} rows={8} className="font-mono text-xs" />
      </Field>
      <div className="flex gap-2">
        <Button size="sm" disabled={busy !== null} onClick={() => void draft()}>
          {busy === 'draft' ? t('catalog.studio.drafting') : t('catalog.studio.draft')}
        </Button>
        <Button size="sm" disabled={busy !== null} onClick={() => void tryIt()}>
          {busy === 'try' ? t('catalog.studio.trying') : t('catalog.studio.try')}
        </Button>
      </div>
      <Field label={t('catalog.studio.spec')} hint={t('catalog.studio.specHint')}>
        <Textarea
          value={specText}
          onChange={(e) => setSpecText(e.target.value)}
          rows={14}
          className="font-mono text-xs"
        />
      </Field>
      {problems.length > 0 && (
        <Notice tone="critical">
          <ul className="list-disc pl-5">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Notice>
      )}
      {result && (
        <div className="rounded-md border border-border p-3 text-sm">
          <div className="font-medium text-text">{t('catalog.studio.result')}</div>
          <p className="text-xs text-text-2">
            {t('catalog.studio.resultLine', {
              detect: result.summary.detect as number,
              programs: metrics.programs ?? 0,
              statements: metrics.statements ?? 0,
              tables: metrics.tables ?? 0,
              business: classification.business ?? 0,
              control: classification.control_flow ?? 0,
              infra: classification.infrastructure ?? 0,
            })}
          </p>
          {((result.summary.programs as { name: string }[]) ?? []).length > 0 && (
            <p className="mt-1 text-xs text-muted">
              {t('catalog.studio.programs')}:{' '}
              {((result.summary.programs as { name: string }[]) ?? []).map((p) => p.name).join(', ')}
            </p>
          )}
          {((result.summary.problems as string[]) ?? []).length > 0 && (
            <p className="mt-1 text-xs text-warning-ink">
              {((result.summary.problems as string[]) ?? []).slice(0, 5).join(' · ')}
            </p>
          )}
        </div>
      )}
      <Notice tone="info">{t('catalog.studio.experimentalNotice')}</Notice>
    </Drawer>
  )
}
