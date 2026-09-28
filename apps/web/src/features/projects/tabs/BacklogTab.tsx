import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bug, CheckCircle2, CheckSquare, Layers, Link2, RefreshCw, Sparkles, SquareStack } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { bugLoop, workItems, type WorkItem, type WorkItemStatus, type WorkItemType } from '@/mocks/data'
import type { Project } from '@/mocks/types'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, StatTile, Toggle } from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'
import { Notice } from '../NewProjectWizard'

// Work items synced with Jira or Azure DevOps (spec 7.6). Agents create and update items; the tester opens bugs
// and the developer agent fixes them automatically within the project's autonomy and iteration limits.

const typeIcon: Record<WorkItemType, typeof Layers> = { feature: Layers, story: SquareStack, task: CheckSquare, bug: Bug }
const statusTone: Record<WorkItemStatus, 'neutral' | 'info' | 'warning' | 'good' | 'critical'> = {
  todo: 'neutral',
  inProgress: 'info',
  inReview: 'warning',
  done: 'good',
  failed: 'critical',
}
const RULES = ['createFromSpec', 'markDone', 'bugOnFailure', 'autoFix', 'retestAndClose', 'syncComments'] as const

export function BacklogTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const [provider, setProvider] = useState<'jira' | 'azureDevOps'>('jira')
  const [rules, setRules] = useState<Record<(typeof RULES)[number], boolean>>({
    createFromSpec: true,
    markDone: true,
    bugOnFailure: true,
    autoFix: true,
    retestAndClose: true,
    syncComments: false,
  })
  const [type, setType] = useState<'all' | WorkItemType>('all')
  const [selectedBug, setSelectedBug] = useState('CARDS-107')
  const items = workItems.filter((w) => type === 'all' || w.type === type)
  const roots = workItems.filter((w) => !w.parent)
  const count = (ty: WorkItemType) => workItems.filter((w) => w.type === ty).length
  const openBugs = workItems.filter((w) => w.type === 'bug' && w.status !== 'done').length

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile label={t('backlog.types.feature')} value={count('feature')} />
        <StatTile label={t('backlog.types.story')} value={count('story')} />
        <StatTile label={t('backlog.types.task')} value={count('task')} />
        <StatTile label={t('backlog.openBugs')} value={openBugs} hint={t('backlog.openBugsHint')} />
        <StatTile label={t('backlog.done')} value={`${workItems.filter((w) => w.status === 'done').length} / ${workItems.length}`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('backlog.connection')} subtitle={t('backlog.connectionHint')} action={<Badge tone="good">{t('common.connected')}</Badge>} />
          <CardBody className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t('backlog.provider')}>
                <Select value={provider} onChange={(e) => setProvider(e.target.value as typeof provider)}>
                  <option value="jira">Jira (Cloud / Data Center)</option>
                  <option value="azureDevOps">Azure DevOps Boards</option>
                </Select>
              </Field>
              <Field label={provider === 'jira' ? t('backlog.site') : t('backlog.organization')}>
                <Input defaultValue={provider === 'jira' ? 'andesbank.atlassian.net' : 'dev.azure.com/andesbank'} />
              </Field>
              <Field label={t('backlog.project')}>
                <Input defaultValue={provider === 'jira' ? 'CARDS' : 'Card Management'} />
              </Field>
              <Field label={t('backlog.lastSync')}>
                <Input value={formatDateTime('2026-09-28T09:36:00Z')} readOnly />
              </Field>
            </div>
            <div className="rounded-md bg-surface-2 p-3 text-xs text-text-2">
              <div className="mb-1 font-medium text-text">{t('backlog.mapping')}</div>
              {(['feature', 'story', 'task', 'bug'] as const).map((ty) => (
                <div key={ty} className="flex justify-between">
                  <span>{t(`backlog.types.${ty}`)}</span>
                  <span className="font-mono">{t(`backlog.mapTo.${provider}.${ty}`)}</span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => toast(t('backlog.synced'))}>
                <RefreshCw size={14} /> {t('backlog.syncNow')}
              </Button>
              <Button size="sm" variant="primary" onClick={() => toast(t('backlog.generated'))}>
                <Sparkles size={14} /> {t('backlog.generate')}
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t('backlog.automation')} subtitle={t('backlog.automationHint')} />
          <CardBody className="space-y-3">
            {RULES.map((r) => (
              <div key={r}>
                <Toggle checked={rules[r]} onChange={(v) => setRules({ ...rules, [r]: v })} label={<span className="font-medium">{t(`backlog.rules.${r}.name`)}</span>} />
                <p className="mt-0.5 ml-12 text-xs text-muted">{t(`backlog.rules.${r}.hint`)}</p>
              </div>
            ))}
            <Notice tone="info">{t('backlog.limitsNote', { max: 3 })}</Notice>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title={t('backlog.items')}
          subtitle={t('backlog.itemsHint', { project: project.name })}
          action={
            <div className="w-44 shrink-0">
            <Select className="h-9" value={type} onChange={(e) => setType(e.target.value as typeof type)} aria-label={t('backlog.filterType')}>
              <option value="all">{t('backlog.allTypes')}</option>
              {(['feature', 'story', 'task', 'bug'] as const).map((ty) => (
                <option key={ty} value={ty}>
                  {t(`backlog.types.${ty}`)}
                </option>
              ))}
            </Select>
            </div>
          }
        />
        <ul className="divide-y divide-border">
          {(type === 'all' ? roots.flatMap((r) => [r, ...descendants(r.key)]) : items).map((w) => (
            <ItemRow key={w.key} item={w} depth={type === 'all' ? depthOf(w) : 0} onBug={() => setSelectedBug(w.key)} selected={selectedBug === w.key} />
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader title={t('backlog.bugLoop', { key: selectedBug })} subtitle={t('backlog.bugLoopHint')} />
        <CardBody>
          <ol className="relative space-y-4 border-l border-border pl-6">
            {bugLoop.map((s) => (
              <li key={s.step} className="relative">
                <span className="absolute top-0.5 -left-[31px] rounded-full bg-surface p-0.5">
                  {s.step === 'detected' ? <Bug size={14} className="text-critical" /> : s.step === 'waitingReview' ? <Link2 size={14} className="text-warning" /> : <CheckCircle2 size={14} className="text-good" />}
                </span>
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="text-xs text-muted tabular">{s.time}</span>
                  <span className="font-medium text-text">{s.agent}</span>
                  <span className="text-text-2">{t(`backlog.loopSteps.${s.step}`)}</span>
                </div>
                <p className="mt-0.5 text-sm text-text-2">{s.detail}</p>
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>
    </div>
  )
}

function descendants(key: string): WorkItem[] {
  return workItems.filter((w) => w.parent === key).flatMap((c) => [c, ...descendants(c.key)])
}

function depthOf(item: WorkItem): number {
  let d = 0
  let p = item.parent
  while (p) {
    d++
    p = workItems.find((w) => w.key === p)?.parent
  }
  return d
}

function ItemRow({ item, depth, onBug, selected }: { item: WorkItem; depth: number; onBug: () => void; selected: boolean }) {
  const { t } = useTranslation()
  const Icon = typeIcon[item.type]
  return (
    <li className={cn('flex flex-wrap items-center gap-3 px-5 py-2.5', item.type === 'bug' && selected && 'bg-critical/5')} style={{ paddingLeft: 20 + depth * 24 }}>
      <Icon size={16} className={cn(item.type === 'bug' ? 'text-critical' : item.type === 'feature' ? 'text-series-1' : 'text-muted')} aria-label={t(`backlog.types.${item.type}`)} />
      <span className="font-mono text-xs text-info">{item.key}</span>
      <span className="min-w-0 flex-1 truncate text-sm text-text">{item.title}</span>
      {item.rules.map((r) => (
        <span key={r} className="hidden font-mono text-[11px] text-muted md:inline">
          {r}
        </span>
      ))}
      <span className="hidden text-xs text-muted sm:inline">{item.assignee}</span>
      <Badge tone={statusTone[item.status]}>{t(`backlog.status.${item.status}`)}</Badge>
      {!item.synced && <Badge tone="warning">{t('backlog.pendingSync')}</Badge>}
      {item.type === 'bug' && (
        <button onClick={onBug} className="text-xs font-medium text-info hover:underline">
          {t('backlog.viewLoop')}
        </button>
      )}
    </li>
  )
}
