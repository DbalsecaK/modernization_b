import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import type { ProjectDetail } from '@/api/projects'
import { downloadEvent, useActivityStream } from '@/api/runs'
import { Badge, Card, CardHeader, EmptyState } from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'

// The project's activity (spec 18.8): the live events of its runs, each one downloadable as JSON without secrets.
export function ProjectActivity({ project }: { project: ProjectDetail }) {
  const { t } = useTranslation()
  const { events, connected } = useActivityStream()
  const mine = events.filter((e) => e.projectId === project.id)
  if (mine.length === 0) return <EmptyState title={t('project.later.activity')} description={t('project.laterHint')} />
  return (
    <Card>
      <CardHeader title={t('project.tabs.activity')} subtitle={connected ? t('runs.live') : undefined} />
      <ul className="divide-y divide-border" aria-live="polite">
        {mine.map((e) => (
          <li key={e.id} className="flex flex-wrap items-start gap-3 px-5 py-3 text-sm">
            <span className="w-40 shrink-0 text-xs text-muted tabular">{formatDateTime(e.occurredAt)}</span>
            <Badge
              tone={
                e.status === 'failed'
                  ? 'critical'
                  : e.status === 'waiting'
                    ? 'warning'
                    : e.status === 'succeeded'
                      ? 'good'
                      : 'info'
              }
            >
              {t(`activity.panel.status.${e.status}`)}
            </Badge>
            <span className="min-w-0 flex-1 text-text-2">
              {e.agentKey && <span className="mr-1 font-medium text-text">{e.agentKey}</span>}
              {e.message}
            </span>
            <button
              className="inline-flex items-center gap-1 text-xs text-text-2 underline"
              onClick={() => downloadEvent(e.id).catch(() => toast(t('common.error')))}
            >
              <Download size={12} /> JSON
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
