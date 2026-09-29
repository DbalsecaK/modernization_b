import { useTranslation } from 'react-i18next'
import { ArrowRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatUsd } from '@/lib/format'
import { useCatalog, useInputs, type ProjectDetail } from '@/api/projects'
import { useRun, useRuns } from '@/api/runs'
import { Badge, Button, Card, CardBody, CardHeader, StatTile } from '@/components/ui/primitives'
import { agentName } from '@/features/catalog/AgentCard'
import { Notice } from '../NewProjectWizard'
import type { ProjectTab } from '../ProjectWorkspace'

export function ProjectOverview({ project, onOpen }: { project: ProjectDetail; onOpen: (tab: ProjectTab) => void }) {
  const { t, i18n } = useTranslation()
  const catalog = useCatalog()
  const inputs = useInputs(project.id)
  const flow = catalog.data?.flows.find((f) => f.key === project.flow)
  const template = catalog.data?.pipelineTemplates.find((x) => x.key === project.config?.pipelineTemplate)
  const accepted = (inputs.data ?? []).filter((i) => i.status === 'accepted')
  const rejected = (inputs.data ?? []).filter((i) => i.status === 'rejected')
  const optionName = (axis: string, key: string) =>
    catalog.data?.targets.find((o) => o.axis === axis && o.key === key)?.name ?? key
  const sourceName = (key: string) => catalog.data?.sources.find((s) => s.key === key)?.name ?? key
  // The pipeline as the latest run left it (spec 18.4).
  const runs = useRuns(project.id)
  const latest = runs.data?.[0]
  const run = useRun(project.id, latest?.id ?? null)
  const phaseStatus = (key: string) => run.data?.phases.find((p) => p.phase === key)?.status ?? 'pending'

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title={t('overview.pipeline')} subtitle={t('overview.pipelineHint')} />
        <CardBody>
          <ol className="flex gap-2 overflow-x-auto pb-2" tabIndex={0} aria-label={t('overview.pipeline')}>
            {(flow?.phases ?? []).map((phase, i, all) => (
              <li key={phase.key} className="flex items-center gap-2">
                <div
                  className={cn(
                    'min-w-32 rounded-md border px-3 py-2',
                    phaseStatus(phase.key) === 'pending' ? 'border-dashed border-border' : 'border-border',
                    phaseStatus(phase.key) === 'succeeded' && 'bg-good/8',
                    phaseStatus(phase.key) === 'running' && 'bg-info/8',
                    ['waiting', 'unavailable'].includes(phaseStatus(phase.key)) && 'bg-warning/8',
                    phaseStatus(phase.key) === 'failed' && 'bg-critical/8',
                  )}
                >
                  <div className="flex items-center gap-1.5 text-xs text-muted">
                    {t(`runsPage.phaseStatus.${phaseStatus(phase.key)}`)}
                    {phase.gate && (
                      <Badge
                        className="ml-auto"
                        tone={template?.requiredGates.includes(phase.gate) ? 'brand' : 'neutral'}
                      >
                        {phase.gate}
                      </Badge>
                    )}
                  </div>
                  <div className="mt-1 text-sm font-medium whitespace-nowrap text-text">{t(`phases.${phase.key}`)}</div>
                </div>
                {i < all.length - 1 && <ArrowRight size={14} className="shrink-0 text-muted" />}
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs text-muted">
            {latest
              ? t('overview.latestRun', { status: t(`runsPage.status.${latest.status}`) })
              : t('overview.noRunYet')}{' '}
            <button className="font-medium text-text underline" onClick={() => onOpen('runs')}>
              {t('overview.open')}
            </button>
          </p>
        </CardBody>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('projectSettings.agents')} value={project.agents.length} />
        <StatTile label={t('projectSettings.skills')} value={project.skills.length} />
        <StatTile
          label={t('inputs.title')}
          value={accepted.length}
          hint={rejected.length ? t('overview.rejectedInputs', { count: rejected.length }) : undefined}
        />
        <StatTile label={t('wizard.budget')} value={project.budgetUsd ? formatUsd(Number(project.budgetUsd)) : '—'} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('overview.nextSteps')} />
          <CardBody className="space-y-3 text-sm">
            {accepted.length === 0 && (
              <NextStep text={t('overview.addInputs')} action={t('overview.open')} onClick={() => onOpen('inputs')} />
            )}
            {rejected.length > 0 && (
              <NextStep
                text={t('overview.fixInputs', { count: rejected.length })}
                action={t('overview.open')}
                onClick={() => onOpen('inputs')}
              />
            )}
            <NextStep text={t('overview.reviewTeam')} action={t('overview.open')} onClick={() => onOpen('settings')} />
            {(project.config?.warnings ?? []).map((w) => (
              <Notice key={w} tone="warning">
                {t(`compat.${w}`)}
              </Notice>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('overview.stack')} />
          <CardBody>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div className="col-span-2">
                <dt className="text-xs text-muted">{t('overview.source')}</dt>
                <dd className="text-text">{(project.config?.sources ?? []).map(sourceName).join(', ') || '—'}</dd>
              </div>
              {project.config &&
                (['architecture', 'backend', 'frontend', 'database', 'cloud'] as const).map((axis) => (
                  <div key={axis}>
                    <dt className="text-xs text-muted">{t(`target.${axis}`)}</dt>
                    <dd className="text-text">
                      {project.config!.target[axis] === 'none'
                        ? t('wizard.noFrontend')
                        : optionName(axis, project.config!.target[axis])}
                    </dd>
                  </div>
                ))}
              <div>
                <dt className="text-xs text-muted">{t('wizard.artifactLanguage')}</dt>
                <dd className="text-text">{project.artifactLanguage === 'en' ? 'English' : 'Español'}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t('projectSettings.pipeline')}</dt>
                <dd className="text-text">
                  {template ? t(`templates.${template.key}.name`, { defaultValue: template.name }) : '—'}
                </dd>
              </div>
            </dl>
            {project.team.length > 0 && (
              <div className="mt-4 border-t border-border pt-3">
                <div className="mb-2 text-xs text-muted">{t('wizard.teamTitle')}</div>
                <ul className="space-y-1 text-sm">
                  {project.team.map((m) => (
                    <li key={`${m.userId}-${m.roleKey}`} className="flex justify-between gap-2">
                      <span className="text-text">{m.displayName}</span>
                      <span className="text-muted">{t(`roles.${m.roleKey}`, { defaultValue: m.roleName })}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {project.agents.length > 0 && (
              <p className="mt-3 text-xs text-muted">
                {project.agents
                  .map((a) => {
                    const agent = catalog.data?.agents.find((x) => x.key === a.key)
                    return agent ? agentName(agent, i18n.language) : a.key
                  })
                  .join(' · ')}
              </p>
            )}
          </CardBody>
        </Card>
      </div>
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
