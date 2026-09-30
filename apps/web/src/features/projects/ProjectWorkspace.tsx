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
import { ProjectRuns } from './workspace/ProjectRuns'
import { ProjectActivity } from './workspace/ProjectActivity'
import { ProjectSpecification } from './workspace/ProjectSpecification'
import { ProjectTraceability } from './workspace/ProjectTraceability'
import { ProjectValidation } from './workspace/ProjectValidation'
import { ProjectUiDesign } from './workspace/ProjectUiDesign'
import { ProjectInventory } from './workspace/ProjectInventory'

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
// Connected so far (M2: overview, inputs, settings; M3: runs, activity; M4: specification, traceability, validation;
// M5: uiDesign; M6: inventory);
// the others fill in as the pipeline produces their content.
const CONNECTED: ProjectTab[] = [
  'overview',
  'inputs',
  'inventory',
  'specification',
  'uiDesign',
  'traceability',
  'validation',
  'runs',
  'activity',
  'settings',
]

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
          <Button variant="primary" onClick={() => setTab('runs')}>
            <Play size={16} /> {t('project.openRuns')}
          </Button>
        }
      />
      <Tabs tabs={visibleTabs.map((id) => ({ id, label: t(`project.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {tab === 'overview' && <ProjectOverview project={p} onOpen={setTab} />}
      {tab === 'inputs' && <ProjectInputs project={p} />}
      {tab === 'inventory' && <ProjectInventory project={p} onOpenRuns={() => setTab('runs')} />}
      {tab === 'specification' && <ProjectSpecification project={p} onOpenRuns={() => setTab('runs')} />}
      {tab === 'uiDesign' && <ProjectUiDesign project={p} onOpenRuns={() => setTab('runs')} />}
      {tab === 'traceability' && <ProjectTraceability project={p} onOpenRuns={() => setTab('runs')} />}
      {tab === 'validation' && <ProjectValidation project={p} onOpenRuns={() => setTab('runs')} />}
      {tab === 'runs' && <ProjectRuns project={p} />}
      {tab === 'activity' && <ProjectActivity project={p} />}
      {tab === 'settings' && <ProjectSettings project={p} />}
      {!CONNECTED.includes(tab) && (
        <EmptyState title={t(`project.later.${tab}`)} description={t('project.laterHint')} />
      )}
    </>
  )
}
