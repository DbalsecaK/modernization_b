import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, FileArchive, FileText, GitBranch, Image, PenTool, Upload } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatCompact, formatDateTime, formatUsd } from '@/lib/format'
import type { Project } from '@/mocks/types'
import { KnowledgeGraph } from '../graph/KnowledgeGraph'
import { Badge, Button, Card, CardBody, CardHeader, Progress, StatTile, Table, Td, Th } from '@/components/ui/primitives'
import { PhaseStatusIcon } from '@/components/ui/status'
import type { ProjectTab } from '../ProjectWorkspace'
import { AddInputForm } from '../InputForms'
import { useNavigate } from '@tanstack/react-router'
import { useStories } from '../stories/store'

export function OverviewTab({ project, onOpen }: { project: Project; onOpen: (tab: ProjectTab) => void }) {
  const { t } = useTranslation()
  const current = project.phases.find((p) => p.status !== 'done')
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title={t('overview.pipeline')} subtitle={t('overview.pipelineHint')} />
        <CardBody>
          <ol className="flex gap-2 overflow-x-auto pb-2">
            {project.phases.map((phase, i) => (
              <li key={phase.key} className="flex items-center gap-2">
                <div
                  className={cn(
                    'min-w-32 rounded-md border px-3 py-2',
                    phase.status === 'waiting' && 'border-warning bg-warning/8',
                    phase.status === 'running' && 'border-info bg-info/8',
                    phase.status === 'done' && 'border-border',
                    phase.status === 'pending' && 'border-dashed border-border',
                  )}
                >
                  <div className="flex items-center gap-1.5 text-xs text-muted">
                    <PhaseStatusIcon status={phase.status} size={12} />
                    {t(`phaseStatus.${phase.status}`)}
                    {phase.gate && <Badge className="ml-auto">{phase.gate}</Badge>}
                  </div>
                  <div className="mt-1 text-sm font-medium whitespace-nowrap text-text">{t(`phases.${phase.key}`)}</div>
                </div>
                {i < project.phases.length - 1 && <ArrowRight size={14} className="shrink-0 text-muted" />}
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('overview.progress')} value={`${project.progress}%`} hint={<Progress value={project.progress} />} />
        <StatTile label={t('overview.rules')} value={`${project.rules.approved} / ${project.rules.total}`} hint={t('overview.rulesHint', { verified: project.rules.verified })} />
        <StatTile label={t('overview.openQuestions')} value={project.openQuestions} />
        <StatTile label={t('overview.tokens')} value={formatCompact(project.tokens)} hint={formatUsd(project.costUsd)} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('overview.nextSteps')} />
          <CardBody className="space-y-3 text-sm">
            {current?.status === 'waiting' && (
              <NextStep text={t('overview.gateWaiting', { gate: current.gate, phase: t(`phases.${current.key}`) })} action={t('overview.review')} onClick={() => onOpen(current.key === 'ui' ? 'uiDesign' : 'specification')} />
            )}
            {project.flow === 'modernization' && <StoriesStep />}
            {project.openQuestions > 0 && <NextStep text={t('overview.answerQuestions', { count: project.openQuestions })} action={t('overview.open')} onClick={() => onOpen('specification')} />}
            <NextStep text={t('overview.checkRuns')} action={t('overview.open')} onClick={() => onOpen('runs')} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('overview.stack')} />
          <CardBody>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted">{t('overview.source')}</dt>
                <dd className="text-text">{project.sources.join(', ')}</dd>
              </div>
              {(Object.keys(project.target) as (keyof Project['target'])[]).map((k) => (
                <div key={k}>
                  <dt className="text-xs text-muted">{t(`target.${k}`)}</dt>
                  <dd className="text-text">{project.target[k]}</dd>
                </div>
              ))}
              <div>
                <dt className="text-xs text-muted">{t('wizard.artifactLanguage')}</dt>
                <dd className="text-text">{project.artifactLanguage === 'en' ? 'English' : 'Español'}</dd>
              </div>
            </dl>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

// Before the migration starts, the user stories and the migration plan are reviewed and approved at C1 (spec 7.7).
function StoriesStep() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { stories, approved } = useStories()
  const pending = stories.filter((s) => s.status === 'draft' || s.status === 'inReview' || s.status === 'question').length
  if (approved || pending === 0) return null
  const open = (view: 'stories' | 'plan') => void navigate({ to: '.', search: ((prev: Record<string, unknown>) => ({ ...prev, tab: 'specification', view })) as never })
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-warning/60 bg-warning/5 p-3">
      <span className="flex-1 text-text-2">{t('overview.reviewStories', { count: pending })}</span>
      <Button size="sm" onClick={() => open('stories')}>
        {t('overview.openStories')}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => open('plan')}>
        {t('overview.openPlan')}
      </Button>
    </div>
  )
}

function NextStep({ text, action, onClick }: { text: string; action: string; onClick: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border p-3">
      <span className="flex-1 text-text-2">{text}</span>
      <Button size="sm" onClick={onClick}>
        {action}
      </Button>
    </div>
  )
}

const inputs = {
  modernization: [
    { name: 'carddemo-cics (main)', kind: 'git', size: '1,240 files', version: 'a41f9c2', at: '2026-09-18T14:00:00Z', status: 'scanned' },
    { name: 'db2-ddl.zip', kind: 'zip', size: '2.1 MB', version: 'v1', at: '2026-09-18T14:05:00Z', status: 'scanned' },
    { name: 'golden-master-traces-2026-09.zip', kind: 'zip', size: '48 MB', version: 'v2', at: '2026-09-25T10:30:00Z', status: 'quarantined' },
  ],
  newFeature: [
    { name: 'ONB-101 … ONB-142 (Jira)', kind: 'doc', size: '42 stories', version: 'sync 09-27', at: '2026-09-27T20:00:00Z', status: 'scanned' },
    { name: 'onboarding.fig', kind: 'figma', size: '8 frames', version: 'v14', at: '2026-09-27T21:05:00Z', status: 'scanned' },
    { name: 'user-manual-v3.pdf', kind: 'doc', size: '36 pages', version: 'v3', at: '2026-09-26T09:00:00Z', status: 'scanned' },
    { name: 'current-onboarding-screens.png', kind: 'image', size: '6 images', version: 'v1', at: '2026-09-26T09:10:00Z', status: 'scanned' },
  ],
}

const kindIcon = { git: GitBranch, zip: FileArchive, doc: FileText, figma: PenTool, image: Image }

export function InputsTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <AddInputForm open={open} onClose={() => setOpen(false)} flow={project.flow} />
      <CardHeader
        title={t('inputs.title')}
        subtitle={t('inputs.subtitle')}
        action={
          <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
            <Upload size={14} /> {t('inputs.add')}
          </Button>
        }
      />
      <Table>
        <thead>
          <tr>
            <Th>{t('inputs.name')}</Th>
            <Th>{t('inputs.size')}</Th>
            <Th>{t('inputs.version')}</Th>
            <Th>{t('inputs.added')}</Th>
            <Th>{t('inputs.status')}</Th>
          </tr>
        </thead>
        <tbody>
          {inputs[project.flow].map((input) => {
            const Icon = kindIcon[input.kind as keyof typeof kindIcon]
            return (
              <tr key={input.name}>
                <Td>
                  <span className="flex items-center gap-2 text-text">
                    <Icon size={16} className="text-muted" /> {input.name}
                  </span>
                </Td>
                <Td>{input.size}</Td>
                <Td className="font-mono text-xs">{input.version}</Td>
                <Td>{formatDateTime(input.at)}</Td>
                <Td>
                  <Badge tone={input.status === 'scanned' ? 'good' : 'warning'}>{t(`inputs.statuses.${input.status}`)}</Badge>
                </Td>
              </tr>
            )
          })}
        </tbody>
      </Table>
      <CardBody>
        <p className="text-xs text-muted">{t('inputs.securityNote')}</p>
      </CardBody>
    </Card>
  )
}

export function InventoryTab({ onCompare }: { onCompare: (ruleId: string) => void }) {
  return <KnowledgeGraph onCompare={onCompare} />
}
