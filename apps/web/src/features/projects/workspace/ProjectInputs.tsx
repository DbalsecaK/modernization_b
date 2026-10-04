import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  FileArchive,
  FileText,
  GitBranch,
  Image,
  Link2,
  Loader2,
  PenTool,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import { ApiError } from '@/api/client'
import {
  hasProjectPermission,
  inputContentUrl,
  useAddLink,
  useDeleteInput,
  useDeleteRepository,
  useInputs,
  useRepository,
  useSetRepository,
  useTestRepository,
  useUploadInput,
  type FileKind,
  type InputItem,
  type ProjectDetail,
} from '@/api/projects'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  Select,
  Table,
  Tabs,
  Td,
  Th,
} from '@/components/ui/primitives'
import { Drawer, Textarea, toast } from '@/components/ui/overlay'
import { Notice } from '../NewProjectWizard'
import { FIGMA_LINK } from '../ProjectSetupSections'

const KIND_ICON = {
  source_archive: FileArchive,
  target_archive: FileArchive,
  document: FileText,
  screenshot: Image,
  figma_link: PenTool,
  prototype_link: Link2,
} as const
const ARCHIVES: readonly string[] = ['source_archive', 'target_archive']
// The files each flow uploads here; the first is the default. Flow 3 (ADR-0026) brings the code of the application it
// extends and the documents of the request; Flow 4 (ADR-0025) brings the legacy code and the third party's target.
const FILE_KINDS: Record<ProjectDetail['flow'], FileKind[]> = {
  modernization: ['source_archive', 'document'],
  newFeature: ['document'],
  independentValidation: ['source_archive', 'target_archive'],
  extendExisting: ['source_archive', 'document'],
}

function useErrorText() {
  const { t } = useTranslation()
  return (error: unknown) =>
    error instanceof ApiError ? t(`inputs.rejections.${error.code}`, { defaultValue: error.message }) : String(error)
}

function formatBytes(bytes: number | null | undefined) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ProjectInputs({ project }: { project: ProjectDetail }) {
  const { t } = useTranslation()
  const inputs = useInputs(project.id)
  const remove = useDeleteInput(project.id)
  const errorText = useErrorText()
  const [open, setOpen] = useState(false)
  const [opened, setOpened] = useState(0)
  const canUpload = hasProjectPermission(project, 'upload')
  const canDownloadCode = hasProjectPermission(project, 'downloadCode')

  async function onDelete(item: InputItem) {
    if (!window.confirm(t('inputs.confirmDelete', { name: item.name }))) return
    try {
      await remove.mutateAsync(item.id)
      toast(t('inputs.deleted', { name: item.name }))
    } catch (error) {
      toast(errorText(error))
    }
  }

  return (
    <div className="space-y-6">
      {project.flow !== 'newFeature' && <RepositoryCard project={project} canEdit={canUpload} />}
      <Card>
        <AddInputDrawer key={opened} project={project} open={open} onClose={() => setOpen(false)} />
        <CardHeader
          title={t('inputs.title')}
          subtitle={t('inputs.subtitle')}
          action={
            canUpload && (
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  setOpened((n) => n + 1)
                  setOpen(true)
                }}
              >
                <Upload size={14} /> {t('inputs.add')}
              </Button>
            )
          }
        />
        {inputs.data?.length === 0 ? (
          <CardBody>
            <p className="text-sm text-muted">{t('inputs.none')}</p>
          </CardBody>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t('inputs.name')}</Th>
                <Th>{t('inputs.size')}</Th>
                <Th>{t('inputs.version')}</Th>
                <Th>{t('inputs.added')}</Th>
                <Th>{t('inputs.status')}</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(inputs.data ?? []).map((item) => {
                const Icon = KIND_ICON[item.kind]
                const secrets = (item.findings as { secrets?: { total?: number } }).secrets?.total ?? 0
                const downloadable =
                  item.status === 'accepted' &&
                  (item.kind === 'document' || (ARCHIVES.includes(item.kind) && canDownloadCode))
                return (
                  <tr key={item.id}>
                    <Td>
                      <span className="flex items-center gap-2 text-text">
                        {item.kind === 'screenshot' && item.status === 'accepted' ? (
                          <img
                            src={inputContentUrl(project.id, item.id)}
                            alt={item.name}
                            className="h-8 w-12 rounded border border-border object-cover"
                          />
                        ) : (
                          <Icon size={16} className="text-muted" />
                        )}
                        {item.url ? (
                          <a href={item.url} target="_blank" rel="noreferrer noopener" className="hover:underline">
                            {item.name}
                          </a>
                        ) : downloadable ? (
                          <a href={inputContentUrl(project.id, item.id)} className="hover:underline">
                            {item.name}
                          </a>
                        ) : (
                          item.name
                        )}
                      </span>
                      <div className="mt-0.5 text-xs text-muted">
                        {t(`inputs.kinds.${item.kind}`)}
                        {item.notes && ` · ${item.notes}`}
                      </div>
                    </Td>
                    <Td className="text-xs">{formatBytes(item.sizeBytes)}</Td>
                    <Td className="font-mono text-xs">
                      {item.version ? `v${item.version}` : '—'}
                      {item.sha256 && <div className="text-muted">{item.sha256.slice(0, 12)}</div>}
                    </Td>
                    <Td className="text-xs">
                      {formatDateTime(item.createdAt)}
                      {item.uploadedByName && <div className="text-muted">{item.uploadedByName}</div>}
                    </Td>
                    <Td>
                      <Badge
                        tone={item.status === 'accepted' ? 'good' : item.status === 'rejected' ? 'critical' : 'neutral'}
                      >
                        {t(`inputs.statuses.${item.status}`)}
                      </Badge>
                      {item.rejectionCode && (
                        <div className="mt-1 max-w-64 text-xs text-text-2">
                          {t(`inputs.rejections.${item.rejectionCode}`, { defaultValue: item.rejectionDetail ?? '' })}
                        </div>
                      )}
                      {secrets > 0 && (
                        <div className="mt-1">
                          <Badge tone="warning">{t('inputs.secretsFound', { count: secrets })}</Badge>
                        </div>
                      )}
                    </Td>
                    <Td className="text-right">
                      {canUpload && item.status === 'accepted' && (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={t('inputs.deleteInput', { name: item.name })}
                          onClick={() => void onDelete(item)}
                        >
                          <Trash2 size={14} />
                        </Button>
                      )}
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        )}
        <CardBody>
          <p className="text-xs text-muted">{t('inputs.securityNote')}</p>
        </CardBody>
      </Card>
    </div>
  )
}

type Source = 'files' | 'screens' | 'figma' | 'prototype'

function AddInputDrawer({ project, open, onClose }: { project: ProjectDetail; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const upload = useUploadInput(project.id)
  const link = useAddLink(project.id)
  const errorText = useErrorText()
  const [source, setSource] = useState<Source>('files')
  const kinds = FILE_KINDS[project.flow]
  const [kind, setKind] = useState<FileKind>(kinds[0])
  const archive = ARCHIVES.includes(kind)
  const [files, setFiles] = useState<File[]>([])
  const [url, setUrl] = useState('')
  const [notes, setNotes] = useState('')
  const [results, setResults] = useState<{ name: string; ok: boolean; detail?: string }[]>([])
  const busy = upload.isPending || link.isPending
  const ready =
    ((source === 'files' || source === 'screens') && files.length > 0) ||
    (source === 'figma' && FIGMA_LINK.test(url.trim())) ||
    (source === 'prototype' && /^https:\/\/\S+\.\S+/.test(url.trim()))

  async function start() {
    const out: typeof results = []
    if (source === 'files' && archive) {
      // One code input: a zip, or the loose code files packed together by the server.
      const label = files.length === 1 ? files[0].name : `${files[0].name} (+${files.length - 1})`
      try {
        await upload.mutateAsync({ file: files, kind, notes })
        out.push({ name: label, ok: true })
      } catch (error) {
        out.push({ name: label, ok: false, detail: errorText(error) })
      }
      setResults([...out])
    } else if (source === 'files' || source === 'screens') {
      for (const file of files) {
        try {
          await upload.mutateAsync({ file, kind: source === 'screens' ? 'screenshot' : kind, notes })
          out.push({ name: file.name, ok: true })
        } catch (error) {
          out.push({ name: file.name, ok: false, detail: errorText(error) })
        }
        setResults([...out])
      }
    } else {
      try {
        await link.mutateAsync({ kind: source === 'figma' ? 'figma_link' : 'prototype_link', url: url.trim(), notes })
        out.push({ name: url.trim(), ok: true })
      } catch (error) {
        out.push({ name: url.trim(), ok: false, detail: errorText(error) })
      }
      setResults(out)
    }
    if (out.every((r) => r.ok)) {
      toast(t('inputForms.added'))
      onClose()
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={t('inputs.add')}
      description={t('inputForms.hint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={!ready || busy} onClick={() => void start()}>
            {busy && <Loader2 size={14} className="animate-spin" />} {t('inputForms.start')}
          </Button>
        </>
      }
    >
      <Tabs
        tabs={(['files', 'screens', 'figma', 'prototype'] as const).map((id) => ({
          id,
          label: t(`inputForms.sources.${id}`),
        }))}
        value={source}
        onChange={(v) => {
          setSource(v)
          setFiles([])
          setUrl('')
          setResults([])
        }}
      />
      {source === 'files' && (
        <Field label={t('inputs.kind')}>
          <Select value={kind} onChange={(e) => setKind(e.target.value as FileKind)}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {t(`inputs.kinds.${k}`)}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {(source === 'files' || source === 'screens') && (
        <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border px-6 py-8 text-center hover:bg-surface-2">
          <Upload size={20} className="text-muted" />
          <span className="text-sm text-text">
            {source === 'screens' ? t('inputForms.dropScreens') : t('inputForms.drop')}
          </span>
          <span className="text-xs text-muted">
            {source === 'screens'
              ? t('inputForms.screensHint')
              : kind === 'target_archive'
                ? t('inputs.targetArchiveHint')
                : archive
                  ? t('inputs.archiveOnly')
                  : t('inputForms.acceptedDocs')}
          </span>
          <input
            type="file"
            multiple
            accept={
              source === 'screens'
                ? 'image/png,image/jpeg,image/webp'
                : archive
                  ? undefined
                  : '.pdf,.docx,.xlsx,.md,.txt'
            }
            className="sr-only"
            aria-label={source === 'screens' ? t('setup.screens') : t('inputForms.drop')}
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
        </label>
      )}
      {files.length > 0 && (
        <ul className="space-y-1 text-xs">
          {files.map((f) => (
            <li key={f.name} className="font-mono text-text">
              {f.name} · {formatBytes(f.size)}
            </li>
          ))}
        </ul>
      )}
      {(source === 'figma' || source === 'prototype') && (
        <Field
          label={source === 'figma' ? t('inputForms.figmaLink') : t('inputForms.prototypeLink')}
          hint={source === 'figma' ? t('setup.invalidLink') : t('inputForms.prototypeHint')}
        >
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={
              source === 'figma'
                ? 'https://www.figma.com/design/AbC123DeF4/Onboarding'
                : 'https://prototype.example.com'
            }
          />
        </Field>
      )}
      <Field label={t('inputForms.prototypeNotes')}>
        <Textarea
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={t('inputForms.prototypeNotesPlaceholder')}
        />
      </Field>
      {results.map((r) => (
        <Notice key={r.name} tone={r.ok ? 'good' : 'critical'}>
          <span className="font-mono text-xs">{r.name}</span> — {r.ok ? t('inputForms.finished') : r.detail}
        </Notice>
      ))}
      <Notice tone="info">{t('inputs.securityNote')}</Notice>
    </Drawer>
  )
}

function RepositoryCard({ project, canEdit }: { project: ProjectDetail; canEdit: boolean }) {
  const { t } = useTranslation()
  const repository = useRepository(project.id)
  const save = useSetRepository(project.id)
  const test = useTestRepository(project.id)
  const remove = useDeleteRepository(project.id)
  const errorText = useErrorText()
  const [editing, setEditing] = useState(false)
  const [url, setUrl] = useState('')
  const [branch, setBranch] = useState('main')
  const [token, setToken] = useState('')
  const [branches, setBranches] = useState<string[]>([])
  const repo = repository.data

  async function submit() {
    try {
      await save.mutateAsync({ url: url.trim(), branch, token: token || null, clearToken: false })
      setEditing(false)
      setToken('')
      toast(t('inputs.repositorySaved'))
    } catch (error) {
      toast(errorText(error))
    }
  }

  async function check() {
    try {
      const result = await test.mutateAsync()
      setBranches(result.branches ?? [])
    } catch (error) {
      toast(errorText(error))
    }
  }

  return (
    <Card>
      <CardHeader
        title={t('inputs.repository')}
        subtitle={t('inputs.repositoryHint')}
        action={
          canEdit &&
          !editing && (
            <Button
              size="sm"
              onClick={() => {
                setUrl(repo?.url ?? '')
                setBranch(repo?.branch ?? 'main')
                setEditing(true)
              }}
            >
              <GitBranch size={14} /> {repo ? t('common.edit') : t('inputs.connectRepository')}
            </Button>
          )
        }
      />
      <CardBody className="space-y-3">
        {editing ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Field label={t('setup.gitUrl')} hint={t('setup.gitUrlHint')}>
                  <Input
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://git.example.com/org/repo.git"
                  />
                </Field>
              </div>
              <Field label={t('setup.gitBranch')}>
                <Input value={branch} onChange={(e) => setBranch(e.target.value)} />
              </Field>
              <Field
                label={t('setup.gitToken')}
                hint={repo?.hasToken ? t('inputs.tokenKept') : t('setup.gitTokenHint')}
              >
                <Input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
              </Field>
            </div>
            <div className="flex gap-2">
              <Button variant="primary" disabled={!url.trim() || save.isPending} onClick={() => void submit()}>
                {t('common.save')}
              </Button>
              <Button variant="ghost" onClick={() => setEditing(false)}>
                {t('common.cancel')}
              </Button>
            </div>
          </>
        ) : repo ? (
          <>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <GitBranch size={16} className="text-muted" />
              <span className="font-mono text-text">{repo.url}</span>
              <Badge>{repo.branch}</Badge>
              {repo.hasToken && <Badge tone="info">{t('inputs.withToken')}</Badge>}
              <Badge tone={repo.status === 'ok' ? 'good' : repo.status === 'failed' ? 'critical' : 'neutral'}>
                {t(`inputs.repositoryStatus.${repo.status}`)}
              </Badge>
            </div>
            {repo.lastCheckDetail && (
              <p className="text-xs text-text-2">
                {repo.lastCheckDetail}
                {repo.lastCheckedAt && ` · ${formatDateTime(repo.lastCheckedAt)}`}
              </p>
            )}
            {branches.length > 0 && (
              <p className="text-xs text-muted">
                {t('inputs.branches', { branches: branches.slice(0, 10).join(', ') })}
              </p>
            )}
            {canEdit && (
              <div className="flex gap-2">
                <Button size="sm" disabled={test.isPending} onClick={() => void check()}>
                  {test.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}{' '}
                  {t('ai.testConnection')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm(t('inputs.confirmRemoveRepository')))
                      void remove.mutateAsync().then(() => toast(t('inputs.repositoryRemoved')))
                  }}
                >
                  <Trash2 size={14} /> {t('common.remove')}
                </Button>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-muted">{t('inputs.noRepository')}</p>
        )}
      </CardBody>
    </Card>
  )
}
