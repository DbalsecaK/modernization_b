import { useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { formatDateTime, formatUsd } from '@/lib/format'
import { projects, tenants } from '@/mocks/data'
import type { Flow } from '@/mocks/types'
import { Badge, Button, Card, EmptyState, Input, PageHeader, Progress, Select, Table, Td, Th } from '@/components/ui/primitives'
import { PhaseStatusIcon, VerdictBadge } from '@/components/ui/status'

export function ProjectsPage() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [flow, setFlow] = useState<'all' | Flow>('all')

  const rows = useMemo(
    () =>
      projects.filter(
        (p) => (flow === 'all' || p.flow === flow) && p.name.toLowerCase().includes(query.toLowerCase().trim()),
      ),
    [query, flow],
  )

  return (
    <>
      <PageHeader
        title={t('projects.title')}
        description={t('projects.description')}
        actions={
          <Link to="/projects/new">
            <Button variant="primary">
              <Plus size={16} /> {t('projects.new')}
            </Button>
          </Link>
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <Input className="max-w-xs" placeholder={t('projects.searchPlaceholder')} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t('common.search')} />
        <Select className="max-w-xs" value={flow} onChange={(e) => setFlow(e.target.value as 'all' | Flow)} aria-label={t('projects.flow')}>
          <option value="all">{t('projects.allFlows')}</option>
          <option value="modernization">{t('flows.modernization')}</option>
          <option value="newFeature">{t('flows.newFeature')}</option>
        </Select>
      </div>
      <Card>
        {rows.length === 0 ? (
          <div className="p-6">
            <EmptyState title={t('projects.emptyTitle')} description={t('projects.emptyBody')} />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t('projects.name')}</Th>
                <Th>{t('projects.flow')}</Th>
                <Th>{t('projects.sourceTarget')}</Th>
                <Th>{t('projects.phase')}</Th>
                <Th>{t('projects.progress')}</Th>
                <Th>{t('projects.verdict')}</Th>
                <Th className="text-right">{t('projects.cost')}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const current = p.phases.find((ph) => ph.status !== 'done') ?? p.phases[p.phases.length - 1]
                return (
                  <tr key={p.id} className="hover:bg-surface-2">
                    <Td>
                      <Link to="/projects/$projectId" params={{ projectId: p.id }} className="font-medium text-text hover:underline">
                        {p.name}
                      </Link>
                      <div className="mt-0.5 text-xs text-muted">
                        {tenants.find((x) => x.id === p.tenantId)?.name} · {t('projects.updated', { date: formatDateTime(p.updatedAt) })}
                      </div>
                    </Td>
                    <Td>
                      <Badge tone={p.flow === 'modernization' ? 'brand' : 'accent'}>{t(`flows.${p.flow}`)}</Badge>
                    </Td>
                    <Td>
                      <div className="text-xs">{p.sources.join(', ')}</div>
                      <div className="text-xs text-muted">→ {p.target.backend} · {p.target.frontend} · {p.target.database}</div>
                    </Td>
                    <Td>
                      <span className="inline-flex items-center gap-1.5 text-xs">
                        <PhaseStatusIcon status={current.status} size={14} />
                        {t(`phases.${current.key}`)}
                      </span>
                    </Td>
                    <Td className="w-36">
                      <Progress value={p.progress} />
                      <div className="mt-1 text-xs text-muted tabular">{p.progress}%</div>
                    </Td>
                    <Td>
                      <VerdictBadge verdict={p.verdict} />
                    </Td>
                    <Td className="text-right tabular">
                      <div className="text-text">{formatUsd(p.costUsd)}</div>
                      <div className="text-xs text-muted">/ {formatUsd(p.budgetUsd)}</div>
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  )
}
