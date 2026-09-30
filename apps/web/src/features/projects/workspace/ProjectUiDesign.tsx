import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, FileCode2, Loader2, MessageSquare, RotateCcw, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { ApiError } from '@/api/client'
import type { ProjectDetail } from '@/api/projects'
import {
  CODE_VIEW,
  PROTOTYPE_COMMENT,
  PROTOTYPE_EDIT,
  prototypePageUrl,
  prototypeSourceUrl,
  screenData,
  useAddComment,
  useComments,
  useDesignSystem,
  usePrototypes,
  useResolveComment,
  useScreens,
  type ScreenData,
} from '@/api/screens'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Select,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'
import { Notice } from '../NewProjectWizard'
import { PrototypeChat } from '../PrototypeChat'
import { dataFields, frameEvent, swatches, terminalRows } from './ui/model'

// Diseño UI tab (spec 7.4, ADR-0013, D-24), connected to the API: the screens the parser read from the legacy maps,
// the legacy terminal screen next to the navigable prototype (fields linked both ways), prototype versions, comments
// anchored to a field, the design system and the change chat. The prototype runs in an iframe with an opaque origin
// (sandbox="allow-scripts", no allow-same-origin) and only talks back through the platform's closed set of messages.
// A person approves the UI at gate C2 in the Runs tab. Same look as the prototype's UiDesignTab.
export function ProjectUiDesign({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const screens = useScreens(project.id)
  const [selected, setSelected] = useState<string | null>(null)
  const [field, setField] = useState<string | null>(null)

  if (screens.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('uiDesign.loading')}
      </p>
    )
  }
  if (screens.isError) {
    return (
      <EmptyState
        title={t('uiDesign.loadError')}
        description={screens.error instanceof ApiError ? screens.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void screens.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  const all = (screens.data ?? []).map(screenData).sort((a, b) => a.id.localeCompare(b.id))
  if (all.length === 0) {
    return (
      <EmptyState
        title={t('uiDesign.emptyTitle')}
        description={t('uiDesign.notYet')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  const screen = all.find((s) => s.id === selected) ?? all[0]
  const select = (id: string) => {
    setSelected(id)
    setField(null)
  }
  const mapsets = [...new Set(all.map((s) => s.mapset).filter(Boolean))]

  return (
    <div className="space-y-6">
      <Notice tone="info">{t('uiDesign.fromBms')}</Notice>
      <Card>
        <CardHeader
          title={t('uiDesign.catalog')}
          subtitle={t('uiDesign.catalogHint', { count: all.length, mapsets: mapsets.join(', ') || '—' })}
        />
        <CardBody>
          <div role="group" aria-label={t('uiDesign.catalog')} className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {all.map((s) => (
              <button
                key={s.id}
                onClick={() => select(s.id)}
                aria-pressed={s.id === screen.id}
                className={cn(
                  'rounded-md border p-3 text-left text-sm transition-colors',
                  s.id === screen.id ? 'border-brand bg-brand/5 dark:border-accent dark:bg-accent/10' : 'border-border',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-muted">{s.id}</span>
                  <Badge>{t('uiDesign.refs.kinds.bms')}</Badge>
                </div>
                <div className="mt-1.5 truncate font-medium text-text">{s.name}</div>
                <div className="truncate text-xs text-muted">
                  {[s.mapset, s.map].filter(Boolean).join(' · ')} ·{' '}
                  {t('uiDesign.fieldCount', { count: dataFields(s).length })}
                </div>
              </button>
            ))}
          </div>
        </CardBody>
      </Card>
      <ScreenDesign
        key={screen.id}
        project={project}
        screen={screen}
        field={field}
        onField={setField}
        onNavigate={(to) => all.some((s) => s.id === to) && select(to)}
      />
      <Card>
        <CardHeader title={t('uiDesign.c2Title')} subtitle={t('uiDesign.c2Hint')} />
        <CardBody className="flex flex-wrap items-center gap-3 text-sm">
          <ShieldCheck size={16} className="shrink-0 text-muted" />
          <p className="min-w-0 flex-1 text-text-2">{t('uiDesign.c2InRuns')}</p>
          <Button size="sm" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}

function ScreenDesign({
  project,
  screen,
  field,
  onField,
  onNavigate,
}: {
  project: ProjectDetail
  screen: ScreenData
  field: string | null
  onField: (name: string | null) => void
  onNavigate: (to: string) => void
}) {
  const { t } = useTranslation()
  const versions = usePrototypes(project.id, screen.id)
  const [chosen, setChosen] = useState<number | null>(null)
  const list = versions.data ?? []
  const current = list.find((v) => v.version === chosen) ?? list[0] ?? null
  const can = (permission: string) => project.permissions.includes(permission)

  return (
    <>
      <div className="grid gap-6 xl:grid-cols-2">
        <LegacyScreen screen={screen} field={field} onField={onField} />
        <Card>
          <CardHeader
            title={t('uiDesign.prototype')}
            subtitle={t('uiDesign.prototypeHint')}
            action={
              current && (
                <div className="flex items-center gap-2">
                  <Select
                    aria-label={t('uiDesign.version')}
                    value={current.version}
                    onChange={(e) => setChosen(Number(e.target.value))}
                  >
                    {list.map((v) => (
                      <option key={v.version} value={v.version}>
                        v{v.version} · {t(`uiDesign.origins.${v.origin}`)}
                      </option>
                    ))}
                  </Select>
                  {can(CODE_VIEW) && (
                    <a
                      href={prototypeSourceUrl(project.id, screen.id, current.version)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-medium text-text-2 hover:text-text hover:underline"
                    >
                      <FileCode2 size={14} /> {t('uiDesign.source')}
                    </a>
                  )}
                </div>
              )
            }
          />
          <CardBody>
            {versions.isLoading ? (
              <p className="flex items-center gap-2 text-sm text-muted" role="status">
                <Loader2 size={16} className="animate-spin" /> {t('uiDesign.loading')}
              </p>
            ) : current ? (
              <PrototypeFrame
                key={current.version}
                src={prototypePageUrl(project.id, screen.id, current.version)}
                title={t('uiDesign.frameTitle', { screen: screen.name, version: current.version })}
                onField={onField}
                onNavigate={onNavigate}
              />
            ) : (
              <p className="text-sm text-muted">{t('uiDesign.noPrototype')}</p>
            )}
            {current && (
              <p className="mt-2 text-xs text-muted">
                {t('uiDesign.versionMeta', { date: formatDateTime(current.createdAt) })}
                {current.notes && ` · ${current.notes}`}
              </p>
            )}
          </CardBody>
        </Card>
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <SpecFields screen={screen} field={field} onField={onField} />
          <DesignSystemCard projectId={project.id} />
        </div>
        {current ? (
          <Comments
            projectId={project.id}
            screen={screen}
            version={current.version}
            field={field}
            canComment={can(PROTOTYPE_COMMENT)}
          />
        ) : (
          <div />
        )}
      </div>
      <PrototypeChat
        projectId={project.id}
        screen={screen.id}
        title={`${screen.name} (${screen.id})`}
        version={current?.version ?? null}
        canEdit={can(PROTOTYPE_EDIT)}
      />
    </>
  )
}

/** The legacy terminal screen drawn from the spec: click a field to link it with the prototype and the comments. */
function LegacyScreen({
  screen,
  field,
  onField,
}: {
  screen: ScreenData
  field: string | null
  onField: (name: string | null) => void
}) {
  const { t } = useTranslation()
  const rows = terminalRows(screen)
  return (
    <Card>
      <CardHeader
        title={t('uiDesign.legacyScreen')}
        subtitle={`${[screen.mapset, screen.map].filter(Boolean).join(' · ')} · ${screen.rows ?? 24}×${screen.columns ?? 80}`}
      />
      <CardBody>
        <div
          className="overflow-x-auto rounded-md bg-black p-4 font-mono text-[11px] leading-5 whitespace-pre text-[#33ff66]"
          role="group"
          aria-label={t('uiDesign.legacyScreen')}
        >
          {rows.map((segments, r) => (
            <div key={r}>
              {segments.map((s, i) =>
                s.field && s.kind !== 'literal' ? (
                  <button
                    key={i}
                    type="button"
                    onClick={() => onField(s.field === field ? null : s.field!)}
                    title={s.field}
                    data-legacy-field={s.field}
                    className={cn(
                      'whitespace-pre',
                      s.kind === 'input' ? 'text-[#ffffff]' : 'text-[#6cf]',
                      s.field === field && 'bg-[#05e194] text-black',
                    )}
                  >
                    {s.text}
                  </button>
                ) : (
                  <span key={i}>{s.text}</span>
                ),
              )}
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">{t('uiDesign.linkHint')}</p>
      </CardBody>
    </Card>
  )
}

/** The prototype in an isolated frame. Messages are accepted only from this frame and only in the closed set. */
function PrototypeFrame({
  src,
  title,
  onField,
  onNavigate,
}: {
  src: string
  title: string
  onField: (name: string) => void
  onNavigate: (to: string) => void
}) {
  const { t } = useTranslation()
  const frame = useRef<HTMLIFrameElement>(null)
  const [state, setState] = useState<{ ready: boolean; error: string | null }>({ ready: false, error: null })

  // The parent keys this component by src: a new version starts with a fresh state.
  useEffect(() => {
    function listen(event: MessageEvent) {
      if (!frame.current || event.source !== frame.current.contentWindow) return
      const message = frameEvent(event.data)
      if (!message) return
      if (message.type === 'ready') setState((s) => ({ ...s, ready: true }))
      else if (message.type === 'field') onField(message.name)
      else if (message.type === 'navigate') onNavigate(message.to)
      else setState((s) => ({ ...s, error: message.message }))
    }
    window.addEventListener('message', listen)
    return () => window.removeEventListener('message', listen)
  }, [onField, onNavigate])

  return (
    <div className="space-y-2">
      {state.error && (
        <p className="flex items-center gap-1 text-xs text-critical" role="alert">
          <AlertTriangle size={14} /> {t('uiDesign.frameError', { message: state.error })}
        </p>
      )}
      <iframe
        ref={frame}
        src={src}
        title={title}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        loading="lazy"
        className="h-[520px] w-full rounded-md border border-border bg-white"
        data-ready={state.ready ? '1' : '0'}
      />
    </div>
  )
}

function SpecFields({
  screen,
  field,
  onField,
}: {
  screen: ScreenData
  field: string | null
  onField: (name: string | null) => void
}) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('uiDesign.fields')} subtitle={t('uiDesign.fieldsHint')} />
      <div className="max-h-80 overflow-y-auto" tabIndex={0} role="region" aria-label={t('uiDesign.fields')}>
        <Table>
          <thead>
            <tr>
              <Th>{t('uiDesign.field')}</Th>
              <Th>{t('uiDesign.kind')}</Th>
              <Th>{t('uiDesign.position')}</Th>
              <Th>{t('uiDesign.length')}</Th>
              <Th>{t('uiDesign.attributes')}</Th>
            </tr>
          </thead>
          <tbody>
            {dataFields(screen).map((f) => (
              <tr
                key={f.name}
                onClick={() => onField(f.name === field ? null : f.name)}
                className={cn('cursor-pointer', f.name === field && 'bg-accent/10')}
                aria-selected={f.name === field}
              >
                <Td className="font-mono text-xs text-text">{f.name}</Td>
                <Td>
                  <Badge tone={f.kind === 'input' ? 'info' : 'neutral'}>{t(`uiDesign.kinds.${f.kind}`)}</Badge>
                </Td>
                <Td className="font-mono text-xs">{f.position ? `${f.position.row},${f.position.column}` : '—'}</Td>
                <Td className="font-mono text-xs">{f.length}</Td>
                <Td className="text-xs">{(f.attributes ?? []).join(', ') || '—'}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </Card>
  )
}

function DesignSystemCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const system = useDesignSystem(projectId)
  if (!system.data) return null
  return (
    <Card>
      <CardHeader
        title={t('uiDesign.designSystem')}
        subtitle={t('uiDesign.designSystemMeta', {
          version: system.data.version,
          source: t(`uiDesign.dsSources.${system.data.source}`),
        })}
      />
      <CardBody className="flex flex-wrap gap-3">
        {swatches(system.data.tokens).map(([name, hex]) => (
          <div key={name} className="text-xs">
            <div className="h-10 w-20 rounded-md border border-border" style={{ background: hex }} />
            <div className="mt-1 font-medium text-text">{name}</div>
            <div className="font-mono text-muted">{hex}</div>
          </div>
        ))}
      </CardBody>
    </Card>
  )
}

function Comments({
  projectId,
  screen,
  version,
  field,
  canComment,
}: {
  projectId: string
  screen: ScreenData
  version: number
  field: string | null
  canComment: boolean
}) {
  const { t } = useTranslation()
  const comments = useComments(projectId, screen.id, version)
  const add = useAddComment(projectId, screen.id, version)
  const resolve = useResolveComment(projectId, screen.id, version)
  const [body, setBody] = useState('')
  const [anchor, setAnchor] = useState<string>('')
  const target = anchor || field || ''
  const list = [...(comments.data ?? [])].sort((a, b) => Number(a.resolved) - Number(b.resolved))

  function submit() {
    const text = body.trim()
    if (!text) return
    add.mutate(
      { body: text, anchor: target ? { field: target } : {} },
      {
        onSuccess: () => {
          setBody('')
          setAnchor('')
          void comments.refetch()
        },
      },
    )
  }

  return (
    <Card>
      <CardHeader title={t('uiDesign.comments')} subtitle={t('uiDesign.commentsHint', { version })} />
      <CardBody className="space-y-3 text-sm">
        {list.length === 0 && <p className="text-muted">{t('uiDesign.noComments')}</p>}
        {list.map((c) => {
          const on = typeof c.anchor.field === 'string' ? c.anchor.field : null
          return (
            <div key={c.id} className={cn('rounded-md bg-surface-2 p-3', c.resolved && 'opacity-60')}>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-medium text-text">{c.author ?? t('uiDesign.someone')}</span>
                {on && <Badge tone={on === field ? 'brand' : 'neutral'}>{on}</Badge>}
              </div>
              <div className="mt-0.5 text-text-2">{c.body}</div>
              <div className="mt-1 flex items-center justify-between text-[11px] text-muted">
                <span>{formatDateTime(c.createdAt)}</span>
                {canComment && (
                  <button
                    className="inline-flex items-center gap-1 hover:text-text"
                    onClick={() =>
                      resolve.mutate({ id: c.id, resolved: !c.resolved }, { onSuccess: () => void comments.refetch() })
                    }
                  >
                    {c.resolved ? <RotateCcw size={12} /> : <Check size={12} />}
                    {t(c.resolved ? 'uiDesign.reopen' : 'uiDesign.resolve')}
                  </button>
                )}
              </div>
            </div>
          )
        })}
        {canComment && (
          <form
            className="space-y-2 border-t border-border pt-3"
            onSubmit={(e) => {
              e.preventDefault()
              submit()
            }}
          >
            <Select aria-label={t('uiDesign.anchor')} value={target} onChange={(e) => setAnchor(e.target.value)}>
              <option value="">{t('uiDesign.wholeScreen')}</option>
              {dataFields(screen).map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name}
                </option>
              ))}
            </Select>
            <textarea
              value={body}
              maxLength={2000}
              onChange={(e) => setBody(e.target.value)}
              placeholder={t('uiDesign.commentPlaceholder')}
              aria-label={t('uiDesign.commentPlaceholder')}
              rows={3}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:outline-none"
            />
            {add.error && (
              <p className="text-xs text-critical" role="alert">
                {add.error instanceof ApiError ? add.error.message : t('uiDesign.commentFailed')}
              </p>
            )}
            <Button size="sm" variant="primary" type="submit" disabled={!body.trim() || add.isPending}>
              <MessageSquare size={14} /> {t('uiDesign.addComment')}
            </Button>
          </form>
        )}
      </CardBody>
    </Card>
  )
}
