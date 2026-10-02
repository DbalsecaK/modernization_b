import { useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import { canCreateProjects, useMe } from '@/api/session'
import { useCatalog, useProjectList, type Flow } from '@/api/projects'
import { Badge, Button, Card, EmptyState, Input, PageHeader, Select, Table, Td, Th } from '@/components/ui/primitives'

export function ProjectsPage() {
  const { t } = useTranslation()
  const me = useMe()
  const projects = useProjectList()
  const catalog = useCatalog()
  const [query, setQuery] = useState('')
  const [flow, setFlow] = useState<'all' | Flow>('all')
  const [status, setStatus] = useState<'active' | 'archived' | 'all'>('active')
  const name = (axis: string, key: string) =>
    catalog.data?.targets.find((o) => o.axis === axis && o.key === key)?.name ?? key
  const source = (key: string) => catalog.data?.sources.find((s) => s.key === key)?.name ?? key

  const rows = useMemo(
    () =>
      (projects.data ?? []).filter(
        (p) =>
          (flow === 'all' || p.flow === flow) &&
          (status === 'all' || p.status === status) &&
          p.name.toLowerCase().includes(query.toLowerCase().trim()),
      ),
    [projects.data, query, flow, status],
  )

  return (
    <>
      <PageHeader
        title={t('projects.title')}
        description={t('projects.description')}
        actions={
          canCreateProjects(me) && (
            <Link to="/projects/new">
              <Button variant="primary">
                <Plus size={16} /> {t('projects.new')}
              </Button>
            </Link>
          )
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <Input
          className="max-w-xs"
          placeholder={t('projects.searchPlaceholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={t('common.search')}
        />
        <Select
          className="max-w-xs"
          value={flow}
          onChange={(e) => setFlow(e.target.value as 'all' | Flow)}
          aria-label={t('projects.flow')}
        >
          <option value="all">{t('projects.allFlows')}</option>
          <option value="modernization">{t('flows.modernization')}</option>
          <option value="newFeature">{t('flows.newFeature')}</option>
          <option value="independentValidation">{t('flows.independentValidation')}</option>
        </Select>
        <Select
          className="max-w-xs"
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
          aria-label={t('projects.status')}
        >
          <option value="active">{t('projects.statuses.active')}</option>
          <option value="archived">{t('projects.statuses.archived')}</option>
          <option value="all">{t('projects.statuses.all')}</option>
        </Select>
      </div>
      <Card>
        {projects.isSuccess && rows.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title={projects.data.length ? t('projects.emptyTitle') : t('projects.noneTitle')}
              description={projects.data.length ? t('projects.emptyBody') : t('projects.noneBody')}
            />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t('projects.name')}</Th>
                <Th>{t('projects.flow')}</Th>
                <Th>{t('projects.sourceTarget')}</Th>
                <Th>{t('projects.configuration')}</Th>
                <Th>{t('projects.created')}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="hover:bg-surface-2">
                  <Td>
                    <Link
                      to="/projects/$projectId"
                      params={{ projectId: p.id }}
                      className="font-medium text-text hover:underline"
                    >
                      {p.name}
                    </Link>
                    {p.status === 'archived' && <Badge className="ml-2">{t('projects.statuses.archived')}</Badge>}
                    {p.description && <div className="mt-0.5 line-clamp-1 text-xs text-muted">{p.description}</div>}
                  </Td>
                  <Td>
                    <Badge tone={p.flow === 'modernization' ? 'brand' : 'accent'}>{t(`flows.${p.flow}`)}</Badge>
                  </Td>
                  <Td>
                    <div className="text-xs">{p.sources.map(source).join(', ') || '—'}</div>
                    {p.target && (
                      <div className="text-xs text-muted">
                        → {name('backend', p.target.backend)} · {name('frontend', p.target.frontend)} ·{' '}
                        {name('database', p.target.database)} · {name('cloud', p.target.cloud)}
                      </div>
                    )}
                  </Td>
                  <Td className="text-xs">
                    {p.configVersion ? t('projects.configVersion', { version: p.configVersion }) : '—'}
                  </Td>
                  <Td className="text-xs">{formatDateTime(p.createdAt)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  )
}
