import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Circle, Loader2, Upload } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { Flow } from '@/mocks/types'
import { Button, Field, Input, Select, Tabs } from '@/components/ui/primitives'
import { Drawer, Textarea, toast } from '@/components/ui/overlay'
import { Notice } from './NewProjectWizard'

type Source = 'files' | 'git' | 'screens' | 'figma' | 'prototype' | 'jira'

// Validation steps every input goes through before any agent reads it (spec 15.4).
const STEPS = ['received', 'typeAndSize', 'archiveSafety', 'malware', 'secrets', 'versioned'] as const

export function AddInputForm({
  open,
  onClose,
  flow,
  initialSource,
}: {
  open: boolean
  onClose: () => void
  flow: Flow
  initialSource?: Source
}) {
  const { t } = useTranslation()
  const sources: Source[] =
    flow === 'modernization'
      ? ['files', 'git', 'screens', 'figma', 'prototype', 'jira']
      : ['files', 'screens', 'figma', 'prototype', 'jira']
  const [source, setSource] = useState<Source>(initialSource ?? sources[0])
  const [shots, setShots] = useState<{ name: string; url: string }[]>([])
  const [protoUrl, setProtoUrl] = useState('')
  const [devops, setDevops] = useState<'jira' | 'azureDevOps'>('jira')
  const [files, setFiles] = useState<string[]>([])
  const [repo, setRepo] = useState('')
  const [branch, setBranch] = useState('main')
  const [figma, setFigma] = useState('')
  const [jql, setJql] = useState('project = ONB AND type = Story')
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(0)

  useEffect(() => {
    if (!running || done >= STEPS.length) return
    const id = window.setTimeout(() => setDone((d) => d + 1), 450)
    return () => window.clearTimeout(id)
  }, [running, done])

  const ready =
    (source === 'files' && files.length > 0) ||
    (source === 'git' && /^https:\/\/\S+/.test(repo)) ||
    (source === 'figma' && /figma\.com\/(file|design|proto)\//.test(figma)) ||
    (source === 'screens' && shots.length > 0) ||
    (source === 'prototype' && /^https:\/\/\S+/.test(protoUrl)) ||
    (source === 'jira' && jql.trim().length > 0)
  const finished = done >= STEPS.length

  function reset() {
    setRunning(false)
    setDone(0)
    setFiles([])
  }

  return (
    <Drawer
      open={open}
      onClose={() => {
        reset()
        onClose()
      }}
      wide
      title={t('inputs.add')}
      description={t('inputForms.hint')}
      footer={
        finished ? (
          <Button
            variant="primary"
            onClick={() => {
              toast(t('inputForms.added'))
              reset()
              onClose()
            }}
          >
            {t('inputForms.done')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" disabled={!ready || running} onClick={() => setRunning(true)}>
              {running ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} {t('inputForms.start')}
            </Button>
          </>
        )
      }
    >
      <Tabs
        tabs={sources.map((id) => ({ id, label: t(`inputForms.sources.${id}`) }))}
        value={source}
        onChange={(v) => !running && setSource(v)}
      />

      {source === 'files' && (
        <div>
          <label
            className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border px-6 py-10 text-center hover:bg-surface-2"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              setFiles(Array.from(e.dataTransfer.files).map((f) => f.name))
            }}
          >
            <Upload size={22} className="text-muted" />
            <span className="text-sm text-text">{t('inputForms.drop')}</span>
            <span className="text-xs text-muted">
              {t(flow === 'modernization' ? 'inputForms.acceptedCode' : 'inputForms.acceptedDocs')}
            </span>
            <input
              type="file"
              multiple
              className="sr-only"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []).map((f) => f.name))}
            />
          </label>
          {files.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-text">
              {files.map((f) => (
                <li key={f} className="rounded bg-surface-2 px-3 py-1.5 font-mono text-xs">
                  {f}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {source === 'git' && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('inputForms.repoUrl')}>
            <Input
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              placeholder="https://github.com/andesbank/card-management"
            />
          </Field>
          <Field label={t('inputForms.branch')}>
            <Input value={branch} onChange={(e) => setBranch(e.target.value)} />
          </Field>
          <Field label={t('inputForms.credentials')} hint={t('inputForms.credentialsHint')}>
            <Select defaultValue="gh">
              <option value="gh">GitHub — andesbank (integration)</option>
              <option value="ado">Azure DevOps — andesbank (integration)</option>
            </Select>
          </Field>
          <Field label={t('inputForms.paths')} hint={t('inputForms.pathsHint')}>
            <Input placeholder="app/cbl, app/cpy, app/bms" />
          </Field>
        </div>
      )}

      {source === 'figma' && (
        <div className="space-y-4">
          <Field label={t('inputForms.figmaLink')} hint={t('inputForms.figmaHint')}>
            <Input
              value={figma}
              onChange={(e) => setFigma(e.target.value)}
              placeholder="https://www.figma.com/design/AbC123/Onboarding"
            />
          </Field>
          <Field label={t('inputForms.figmaPages')}>
            <Input placeholder="Onboarding flow, Components" />
          </Field>
        </div>
      )}

      {source === 'screens' && (
        <div>
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border px-6 py-8 text-center hover:bg-surface-2">
            <Upload size={22} className="text-muted" />
            <span className="text-sm text-text">{t('inputForms.dropScreens')}</span>
            <span className="text-xs text-muted">{t('inputForms.screensHint')}</span>
            <input
              type="file"
              accept="image/*"
              multiple
              className="sr-only"
              onChange={(e) =>
                setShots(Array.from(e.target.files ?? []).map((f) => ({ name: f.name, url: URL.createObjectURL(f) })))
              }
            />
          </label>
          {shots.length > 0 && (
            <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4">
              {shots.map((s) => (
                <figure key={s.url} className="overflow-hidden rounded-md border border-border">
                  <img src={s.url} alt={s.name} className="aspect-video w-full object-cover" />
                  <figcaption className="truncate px-1.5 py-1 text-[10px] text-muted">{s.name}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </div>
      )}

      {source === 'prototype' && (
        <div className="space-y-4">
          <Field label={t('inputForms.prototypeLink')} hint={t('inputForms.prototypeHint')}>
            <Input
              value={protoUrl}
              onChange={(e) => setProtoUrl(e.target.value)}
              placeholder="https://www.figma.com/proto/… · https://prototype.example.com"
            />
          </Field>
          <Field label={t('inputForms.prototypeNotes')}>
            <Textarea rows={3} placeholder={t('inputForms.prototypeNotesPlaceholder')} />
          </Field>
        </div>
      )}

      {source === 'jira' && (
        <div className="space-y-4">
          <Field label={t('inputForms.devopsProvider')}>
            <Select value={devops} onChange={(e) => setDevops(e.target.value as typeof devops)}>
              <option value="jira">Jira</option>
              <option value="azureDevOps">Azure DevOps Boards</option>
            </Select>
          </Field>
          <Field label={t('inputForms.jiraConnection')}>
            <Select defaultValue="default">
              <option value="default">
                {devops === 'jira'
                  ? 'Jira — andesbank.atlassian.net (integration)'
                  : 'Azure DevOps — dev.azure.com/andesbank (integration)'}
              </option>
            </Select>
          </Field>
          <Field label={devops === 'jira' ? t('inputForms.jql') : t('inputForms.wiql')} hint={t('inputForms.jqlHint')}>
            <Textarea value={jql} onChange={(e) => setJql(e.target.value)} className="min-h-16 font-mono text-xs" />
          </Field>
        </div>
      )}

      {running && (
        <div className="rounded-lg border border-border p-4">
          <div className="mb-3 text-sm font-medium text-text">{t('inputForms.checks')}</div>
          <ol className="space-y-2">
            {STEPS.map((step, i) => (
              <li key={step} className={cn('flex items-center gap-2 text-sm', i < done ? 'text-text' : 'text-muted')}>
                {i < done ? (
                  <CheckCircle2 size={16} className="text-good" />
                ) : i === done ? (
                  <Loader2 size={16} className="animate-spin text-info" />
                ) : (
                  <Circle size={16} />
                )}
                {t(`inputForms.steps.${step}`)}
              </li>
            ))}
          </ol>
          {finished && <p className="mt-3 text-sm text-good-ink">{t('inputForms.finished')}</p>}
        </div>
      )}

      <Notice tone="info">{t('inputs.securityNote')}</Notice>
    </Drawer>
  )
}
