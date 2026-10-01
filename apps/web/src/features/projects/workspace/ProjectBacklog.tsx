import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bug, CheckSquare, ExternalLink, Layers, Link2, RefreshCw, SquareStack, Unlink } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import type { ProjectDetail } from '@/api/projects'
import {
  PROJECT_CONFIGURE,
  useBacklog,
  useLinkBacklog,
  useSyncBacklog,
  useUnlinkBacklog,
  type Backlog,
  type WorkItem,
} from '@/api/backlog'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Select,
  StatTile,
  Table,
  Td,
  Th,
  Toggle,
} from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'
import { errorMessage } from '@/features/admin/AdminForms'
import { Notice } from '../NewProjectWizard'

// The project's backlog in Jira or Azure DevOps (spec 7.6, ADR-0019), connected to the API: the link, the automation
// rules, the items the worker keeps in sync and the corrections the developer agent proposed for bugs.

type Kind = WorkItem['kind']
type Rules = NonNullable<Backlog['link']>['rules']
const ICONS: Record<Kind, typeof Layers> = { feature: Layers, story: SquareStack, task: CheckSquare, bug: Bug }
const TONE = { open: 'neutral', review: 'warning', done: 'good', discarded: 'neutral' } as const
const FIX_TONE = { proposed: 'warning', failed: 'critical', escalated: 'critical' } as const
const RULES = ['createFromSpec', 'markDone', 'bugOnFailure', 'autoFix'] as const
const DEFAULT_RULES: Rules = { createFromSpec: true, markDone: true, bugOnFailure: true, autoFix: true }

function LinkForm({ project, backlog }: { project: ProjectDetail; backlog: Backlog }) {
  const { t } = useTranslation()
  const link = useLinkBacklog(project.id)
  const unlink = useUnlinkBacklog(project.id)
  const current = backlog.link
  const [integrationId, setIntegrationId] = useState(current?.integrationId ?? backlog.connections[0]?.id ?? '')
  const [external, setExternal] = useState(current?.externalProject ?? '')
  const [rules, setRules] = useState<Rules>(current?.rules ?? DEFAULT_RULES)
  const chosen = backlog.connections.find((c) => c.id === integrationId)

  async function save() {
    try {
      await link.mutateAsync({ integrationId, externalProject: external.trim(), rules })
      toast(t('backlog.linked'))
    } catch (error) {
      toast(t('backlog.failed', { message: errorMessage(error) }))
    }
  }

  if (backlog.connections.length === 0) {
    return <Notice tone="info">{t('backlog.noConnections')}</Notice>
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('backlog.connectionLabel')}>
          <Select value={integrationId} onChange={(e) => setIntegrationId(e.target.value)}>
            {backlog.connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {t(`integrations.kinds.${c.kind}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label={chosen?.kind === 'azure_devops' ? t('backlog.adoProject') : t('backlog.jiraProject')}
          hint={chosen?.kind === 'azure_devops' ? t('backlog.adoProjectHint') : t('backlog.jiraProjectHint')}
        >
          <Input
            value={external}
            onChange={(e) => setExternal(e.target.value)}
            placeholder={chosen?.kind === 'azure_devops' ? 'Card Management' : 'CARDS'}
          />
        </Field>
      </div>
      <div className="space-y-3">
        {RULES.map((r) => (
          <div key={r}>
            <Toggle
              checked={rules[r]}
              onChange={(v) => setRules({ ...rules, [r]: v })}
              label={<span className="font-medium">{t(`backlog.rules.${r}.name`)}</span>}
            />
            <p className="mt-0.5 ml-12 text-xs text-muted">{t(`backlog.rules.${r}.hint`)}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={!integrationId || !external.trim() || link.isPending} onClick={save}>
          <Link2 size={14} /> {current ? t('backlog.saveLink') : t('backlog.link')}
        </Button>
        {current && (
          <Button
            variant="ghost"
            onClick={async () => {
              if (!window.confirm(t('backlog.confirmUnlink'))) return
              try {
                await unlink.mutateAsync(undefined)
                toast(t('backlog.unlinked'))
              } catch (error) {
                toast(t('backlog.failed', { message: errorMessage(error) }))
              }
            }}
          >
            <Unlink size={14} /> {t('backlog.unlink')}
          </Button>
        )}
      </div>
    </div>
  )
}

export function ProjectBacklog({ project }: { project: ProjectDetail }) {
  const { t } = useTranslation()
  const backlog = useBacklog(project.id)
  const sync = useSyncBacklog(project.id)
  const [type, setType] = useState<'all' | Kind>('all')
  const canConfigure = project.permissions.includes(PROJECT_CONFIGURE)
  if (backlog.isLoading || !backlog.data) return null
  const data = backlog.data
  const items = data.items.filter((i) => type === 'all' || i.kind === type)
  const count = (kind: Kind) => data.items.filter((i) => i.kind === kind).length
  const openBugs = data.items.filter((i) => i.kind === 'bug' && i.state !== 'done').length

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile label={t('backlog.types.feature')} value={count('feature')} />
        <StatTile label={t('backlog.types.story')} value={count('story')} />
        <StatTile label={t('backlog.types.task')} value={count('task')} />
        <StatTile label={t('backlog.openBugs')} value={openBugs} hint={t('backlog.openBugsHint')} />
        <StatTile
          label={t('backlog.done')}
          value={`${data.items.filter((i) => i.state === 'done').length} / ${data.items.length}`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title={t('backlog.connection')}
            subtitle={t('backlog.connectionHint')}
            action={
              data.link ? (
                <Badge tone="good">{t(`integrations.kinds.${data.link.kind}`)}</Badge>
              ) : (
                <Badge tone="neutral">{t('backlog.notLinked')}</Badge>
              )
            }
          />
          <CardBody className="space-y-4">
            {canConfigure ? (
              <LinkForm key={data.link?.integrationId ?? 'new'} project={project} backlog={data} />
            ) : data.link ? (
              <p className="text-sm text-text-2">
                {data.link.integrationName} · {data.link.externalProject}
              </p>
            ) : (
              <Notice tone="info">{t('backlog.askOwner')}</Notice>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t('backlog.syncTitle')} subtitle={t('backlog.syncHint')} />
          <CardBody className="space-y-4">
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-muted">{t('backlog.lastSync')}</dt>
                <dd className="text-text">{data.link?.lastSyncedAt ? formatDateTime(data.link.lastSyncedAt) : '—'}</dd>
              </div>
              <div>
                <dt className="text-muted">{t('backlog.lastResult')}</dt>
                <dd className="text-text">{data.link?.lastSyncDetail ?? '—'}</dd>
              </div>
            </dl>
            {canConfigure && data.link && (
              <Button
                size="sm"
                disabled={sync.isPending}
                onClick={async () => {
                  try {
                    const queued = await sync.mutateAsync(undefined)
                    toast(queued.queued ? t('backlog.syncQueued') : t('backlog.syncWaiting'))
                  } catch (error) {
                    toast(t('backlog.failed', { message: errorMessage(error) }))
                  }
                }}
              >
                <RefreshCw size={14} /> {t('backlog.syncNow')}
              </Button>
            )}
            <Notice tone="info">{t('backlog.limitsNote')}</Notice>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title={t('backlog.items')}
          subtitle={t('backlog.itemsHint', { project: project.name })}
          action={
            <div className="w-44 shrink-0">
              <Select
                className="h-9"
                value={type}
                onChange={(e) => setType(e.target.value as typeof type)}
                aria-label={t('backlog.filterType')}
              >
                <option value="all">{t('backlog.allTypes')}</option>
                {(['feature', 'story', 'task', 'bug'] as const).map((k) => (
                  <option key={k} value={k}>
                    {t(`backlog.types.${k}`)}
                  </option>
                ))}
              </Select>
            </div>
          }
        />
        <CardBody>
          {items.length === 0 ? (
            <EmptyState title={t('backlog.noItems')} description={t('backlog.noItemsHint')} />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t('backlog.item')}</Th>
                  <Th>{t('backlog.externalKey')}</Th>
                  <Th>{t('backlog.state')}</Th>
                  <Th>{t('backlog.updated')}</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => {
                  const Icon = ICONS[i.kind]
                  return (
                    <tr key={i.element}>
                      <Td>
                        <div className="flex items-center gap-2">
                          <Icon size={14} className="text-muted" aria-hidden />
                          <span className="font-medium text-text">{i.title || i.element}</span>
                        </div>
                        <div className="font-mono text-xs text-muted">{i.element}</div>
                      </Td>
                      <Td>
                        {i.url ? (
                          <a
                            className="inline-flex items-center gap-1 text-primary hover:underline"
                            href={i.url}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {i.externalKey} <ExternalLink size={12} aria-hidden />
                          </a>
                        ) : (
                          i.externalKey
                        )}
                      </Td>
                      <Td>
                        <Badge tone={TONE[i.state]}>{t(`backlog.states.${i.state}`)}</Badge>
                      </Td>
                      <Td className="text-xs">{formatDateTime(i.updatedAt)}</Td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      {data.fixes.length > 0 && (
        <Card>
          <CardHeader title={t('backlog.fixes')} subtitle={t('backlog.fixesHint')} />
          <CardBody>
            <Table>
              <thead>
                <tr>
                  <Th>{t('backlog.item')}</Th>
                  <Th>{t('backlog.iteration')}</Th>
                  <Th>{t('backlog.state')}</Th>
                  <Th>{t('backlog.detail')}</Th>
                </tr>
              </thead>
              <tbody>
                {data.fixes.map((f) => (
                  <tr key={`${f.element}-${f.iteration}`}>
                    <Td className="font-mono text-xs">{f.element}</Td>
                    <Td>{f.iteration}</Td>
                    <Td>
                      <Badge tone={FIX_TONE[f.status]}>{t(`backlog.fixStatus.${f.status}`)}</Badge>
                    </Td>
                    <Td className="max-w-md text-xs whitespace-pre-wrap">{f.detail.slice(0, 400)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </CardBody>
        </Card>
      )}
    </div>
  )
}
