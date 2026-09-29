import { Link, useParams } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, Play } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { formatDate } from '@/lib/format'
import { useProject } from '@/api/projects'
import { Badge, Button, EmptyState, PageHeader, Tabs } from '@/components/ui/primitives'
import { ProjectInputs } from './workspace/ProjectInputs'
import { ProjectOverview } from './workspace/ProjectOverview'
import { ProjectSettings } from './workspace/ProjectSettings'

const TABS = [
  'overview',
  'inputs',
  'inventory',
  'specification',
  'uiDesign',
  'architecture',
  'code',
  'traceability',
  'validation',
  'backlog',
  'runs',
  'costs',
  'activity',
  'settings',
] as const
export type ProjectTab = (typeof TABS)[number]
// Connected in M2; the other tabs fill in as the pipeline produces their content (M3 onwards).
const CONNECTED: ProjectTab[] = ['overview', 'inputs', 'settings']

export function ProjectWorkspace() {
  const { t } = useTranslation()
  const { projectId } = useParams({ strict: false }) as { projectId: string }
  const [tab, setTab] = useTab(TABS, 'overview')
  const project = useProject(projectId)

  if (project.isError) {
    return (
      <EmptyState
        title={t('project.notFound')}
        action={
          <Link to="/projects" className="text-sm text-info hover:underline">
            {t('project.back')}
          </Link>
        }
      />
    )
  }
  if (!project.data) return null
  const p = project.data
  // The inventory tab only applies to modernization projects (the legacy map).
  const visibleTabs = TABS.filter((id) => p.flow === 'modernization' || id !== 'inventory')
  const owners = p.team.filter((m) => m.roleKey === 'projectOwner').map((m) => m.displayName)

  return (
    <>
      <Link to="/projects" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-text">
        <ChevronLeft size={16} /> {t('project.back')}
      </Link>
      <PageHeader
        title={p.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={p.flow === 'modernization' ? 'brand' : 'accent'}>{t(`flows.${p.flow}`)}</Badge>
            {p.status === 'archived' && <Badge>{t('projects.statuses.archived')}</Badge>}
            {owners.length > 0 && <span>{t('project.owner', { name: owners.join(', ') })}</span>}
            <span>·</span>
            <span>{t('project.createdOn', { date: formatDate(p.createdAt) })}</span>
            {p.config && (
              <>
                <span>·</span>
                <span>{t('projects.configVersion', { version: p.config.version })}</span>
              </>
            )}
          </span>
        }
        actions={
          <Button variant="primary" disabled title={t('project.runsLater')}>
            <Play size={16} /> {t('project.runNextPhase')}
          </Button>
        }
      />
      <Tabs tabs={visibleTabs.map((id) => ({ id, label: t(`project.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {tab === 'overview' && <ProjectOverview project={p} onOpen={setTab} />}
      {tab === 'inputs' && <ProjectInputs project={p} />}
      {tab === 'settings' && <ProjectSettings project={p} />}
      {!CONNECTED.includes(tab) && (
        <EmptyState title={t(`project.later.${tab}`)} description={t('project.laterHint')} />
      )}
    </>
  )
}
