import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, Play } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { formatUsd } from '@/lib/format'
import { projects, tenants } from '@/mocks/data'
import { Badge, Button, EmptyState, PageHeader, Tabs } from '@/components/ui/primitives'
import { VerdictBadge } from '@/components/ui/status'
import { InputsTab, InventoryTab, OverviewTab } from './tabs/OverviewTabs'
import { ArchitectureTab, CodeTab, SpecificationTab, TraceabilityTab, UiDesignTab } from './tabs/SpecTabs'
import { BacklogTab } from './tabs/BacklogTab'
import { ActivityTab, CostsTab, RunsTab, SettingsTab, ValidationTab } from './tabs/QualityTabs'

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

export function ProjectWorkspace() {
  const { t } = useTranslation()
  const { projectId } = useParams({ strict: false }) as { projectId: string }
  const [tab, setTab] = useTab(TABS, 'overview')
  const navigate = useNavigate()
  const openCompare = (rule: string) => void navigate({ to: '.', search: { tab: 'traceability', rule } as never })
  const project = projects.find((p) => p.id === projectId)

  if (!project) {
    return <EmptyState title={t('project.notFound')} action={<Link to="/projects" className="text-sm text-info hover:underline">{t('project.back')}</Link>} />
  }

  // The inventory tab only applies to modernization projects (the legacy map).
  const visibleTabs = TABS.filter((id) => project.flow === 'modernization' || id !== 'inventory')

  return (
    <>
      <Link to="/projects" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-text">
        <ChevronLeft size={16} /> {t('project.back')}
      </Link>
      <PageHeader
        title={project.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={project.flow === 'modernization' ? 'brand' : 'accent'}>{t(`flows.${project.flow}`)}</Badge>
            <span>{tenants.find((x) => x.id === project.tenantId)?.name}</span>
            <span>·</span>
            <span>{t('project.owner', { name: project.owner })}</span>
            <span>·</span>
            <span className="tabular">
              {formatUsd(project.costUsd)} / {formatUsd(project.budgetUsd)}
            </span>
            <VerdictBadge verdict={project.verdict} />
          </span>
        }
        actions={
          <Button variant="primary">
            <Play size={16} /> {t('project.runNextPhase')}
          </Button>
        }
      />
      <Tabs tabs={visibleTabs.map((id) => ({ id, label: t(`project.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {tab === 'overview' && <OverviewTab project={project} onOpen={setTab} />}
      {tab === 'inputs' && <InputsTab project={project} />}
      {tab === 'inventory' && <InventoryTab onCompare={openCompare} />}
      {tab === 'specification' && <SpecificationTab project={project} />}
      {tab === 'uiDesign' && <UiDesignTab project={project} />}
      {tab === 'architecture' && <ArchitectureTab project={project} />}
      {tab === 'code' && <CodeTab project={project} />}
      {tab === 'traceability' && <TraceabilityTab />}
      {tab === 'validation' && <ValidationTab project={project} />}
      {tab === 'backlog' && <BacklogTab project={project} />}
      {tab === 'runs' && <RunsTab project={project} />}
      {tab === 'costs' && <CostsTab project={project} />}
      {tab === 'activity' && <ActivityTab project={project} />}
      {tab === 'settings' && <SettingsTab project={project} />}
    </>
  )
}
