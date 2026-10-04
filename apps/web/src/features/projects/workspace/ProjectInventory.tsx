import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import { impactOf, useGraph } from '@/api/graph'
import type { ProjectDetail } from '@/api/projects'
import { Button, EmptyState } from '@/components/ui/primitives'
import { KnowledgeGraph } from '../graph/KnowledgeGraph'
import { ClassificationPanel } from './ClassificationPanel'

// Inventario tab (spec 5.2.1), connected to the API: the knowledge graph the inventory phase wrote, with the rules,
// the migration state and the business flows the server computes. A rule opens the Source ↔ target view.
export function ProjectInventory({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const graph = useGraph(project.id)

  if (graph.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('graph.loading')}
      </p>
    )
  }
  if (graph.isError) {
    const unavailable = graph.error instanceof ApiError && graph.error.status === 503
    return (
      <EmptyState
        title={t(unavailable ? 'graph.unavailable' : 'graph.loadError')}
        description={graph.error instanceof ApiError && !unavailable ? graph.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void graph.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  if (!graph.data || graph.data.nodes.length === 0) {
    return (
      <EmptyState
        title={t('graph.emptyTitle')}
        description={t('project.later.inventory')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  return (
    <div className="space-y-6">
      <KnowledgeGraph
        data={graph.data}
        onImpact={(node) => impactOf(project.id, node)}
        onCompare={(rule) =>
          void navigate({
            to: '.',
            search: (prev: Record<string, unknown>) => ({ ...prev, tab: 'traceability', rule }),
          })
        }
      />
      <ClassificationPanel projectId={project.id} />
    </div>
  )
}
