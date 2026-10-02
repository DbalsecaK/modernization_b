import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import { useDelta } from '@/api/delta'
import type { ProjectDetail } from '@/api/projects'
import { Badge, Button, Card, CardBody, CardHeader, Code, EmptyState, Table, Td, Th } from '@/components/ui/primitives'
import { Notice } from '../NewProjectWizard'
import { fieldLabel, inventoryOf, sourceLabel, type TargetInventoryView } from './ivv/model'
import {
  baselineOf,
  designOf,
  isDeltaEmpty,
  type BaselineView,
  type DeltaChange,
  type DeltaDesignView,
} from './delta/model'

// Delta tab (Flow 3, ADR-0026), connected to the API: the AS-IS inventory of the application the project extends, the
// baseline of its tests before the delta, the delta design approved at C3, the files the delta adds and changes (each
// opens in the Code tab) and DELTA.md. The verdict is in the Validation tab.
export function ProjectDelta({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const delta = useDelta(project.id)

  if (delta.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('delta.loading')}
      </p>
    )
  }
  if (delta.isError) {
    return (
      <EmptyState
        title={t('delta.loadError')}
        description={delta.error instanceof ApiError ? delta.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void delta.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  const data = delta.data
  if (!data || isDeltaEmpty(data)) {
    return (
      <EmptyState
        title={t('delta.emptyTitle')}
        description={t('delta.notYet')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  const inventory = inventoryOf(data.inventory)
  const baseline = baselineOf(data.baseline)
  const design = designOf(data.design)

  return (
    <div className="space-y-6">
      {inventory && <InventoryCard inventory={inventory} />}
      {baseline && <BaselineCard baseline={baseline} />}
      {design && <DesignCard design={design} />}
      {(data.added.length > 0 || data.changed.length > 0) && (
        <FilesCard projectId={project.id} added={data.added} changed={data.changed} />
      )}
      {data.report !== null && (
        <Card>
          <CardHeader title={t('delta.report')} subtitle={t('delta.reportHint')} />
          <CardBody>
            <Code label={t('delta.report')} className="max-h-[32rem] whitespace-pre-wrap">
              {data.report}
            </Code>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

function InventoryCard({ inventory }: { inventory: TargetInventoryView }) {
  const { t } = useTranslation()
  const facts = [
    inventory.mainClass && t('ivv.mainClass', { value: inventory.mainClass }),
    inventory.artifact && t('ivv.artifact', { value: inventory.artifact }),
    inventory.schema && t('ivv.schema', { value: inventory.schema }),
  ].filter(Boolean)
  return (
    <Card>
      <CardHeader
        title={t('delta.inventory')}
        subtitle={t('delta.inventoryHint')}
        action={<Badge tone="info">{inventory.stack}</Badge>}
      />
      {facts.length > 0 && <CardBody className="text-xs text-muted">{facts.join(' · ')}</CardBody>}
      <div className="border-t border-border px-5 pt-4 pb-2 text-sm font-semibold text-text">
        {t('ivv.endpoints', { count: inventory.endpoints.length })}
      </div>
      {inventory.endpoints.length === 0 ? (
        <CardBody className="text-sm text-muted">{t('delta.noEndpoints')}</CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('ivv.endpoint')}</Th>
              <Th>{t('ivv.handler')}</Th>
              <Th>{t('ivv.request')}</Th>
              <Th>{t('ivv.response')}</Th>
            </tr>
          </thead>
          <tbody>
            {inventory.endpoints.map((e) => (
              <tr key={`${e.method} ${e.path}`}>
                <Td className="font-mono text-xs whitespace-nowrap">
                  <Badge>{e.method}</Badge> {e.path}
                </Td>
                <Td className="text-xs">
                  <span className="block text-text">{e.handler}</span>
                  <span className="block font-mono text-muted">{sourceLabel(e)}</span>
                </Td>
                <Td className="font-mono text-xs">{e.request.map(fieldLabel).join(', ') || '—'}</Td>
                <Td className="font-mono text-xs">{e.response.map(fieldLabel).join(', ') || '—'}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <div className="border-t border-border px-5 pt-4 pb-2 text-sm font-semibold text-text">
        {t('ivv.tables', { count: inventory.tables.length })}
      </div>
      {inventory.tables.length === 0 ? (
        <CardBody className="text-sm text-muted">{t('delta.noTables')}</CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('ivv.table')}</Th>
              <Th>{t('ivv.columns')}</Th>
              <Th>{t('ivv.key')}</Th>
            </tr>
          </thead>
          <tbody>
            {inventory.tables.map((tb) => (
              <tr key={tb.name}>
                <Td className="font-mono text-xs">{tb.name}</Td>
                <Td className="font-mono text-xs">{tb.columns.join(', ') || '—'}</Td>
                <Td className="font-mono text-xs">{tb.key.join(', ') || '—'}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function BaselineCard({ baseline }: { baseline: BaselineView }) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader
        title={t('delta.baseline')}
        subtitle={t('delta.baselineHint')}
        action={<Badge tone="good">{t('delta.passing', { count: baseline.passed.length })}</Badge>}
      />
      <CardBody className="space-y-3">
        {baseline.passed.length === 0 && <Notice tone="warning">{t('delta.noTests')}</Notice>}
        {baseline.failed.length > 0 && (
          <div className="space-y-2 rounded-md bg-warning/12 p-3 text-sm">
            <p className="font-medium text-text">{t('delta.alreadyFailing', { count: baseline.failed.length })}</p>
            <p className="text-xs text-muted">{t('delta.alreadyFailingHint')}</p>
            <ul className="list-disc space-y-1 pl-5 font-mono text-xs text-text-2">
              {baseline.failed.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function DesignCard({ design }: { design: DeltaDesignView }) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader
        title={t('delta.design')}
        subtitle={t('delta.designHint')}
        action={<Badge>{t('delta.changes', { count: design.changes.length })}</Badge>}
      />
      <CardBody className="space-y-4">
        {design.changes.length === 0 ? (
          <p className="text-sm text-muted">{t('delta.noChanges')}</p>
        ) : (
          <ul className="space-y-3">
            {design.changes.map((c, i) => (
              <ChangeItem key={`${i}-${c.name}`} change={c} />
            ))}
          </ul>
        )}
        {design.decisions.length > 0 && (
          <section className="space-y-2">
            <h4 className="text-sm font-semibold text-text">{t('delta.decisions')}</h4>
            <ul className="space-y-2 text-sm">
              {design.decisions.map((d, i) => (
                <li key={`${i}-${d.title}`} className="rounded-md border border-border px-3 py-2">
                  <span className="block font-medium text-text">{d.title}</span>
                  <span className="block text-text-2">{d.decision}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </CardBody>
    </Card>
  )
}

function ChangeItem({ change }: { change: DeltaChange }) {
  const { t } = useTranslation()
  const facts: [string, string[]][] = [
    [t('delta.reuses'), change.reuses],
    [t('delta.tables'), change.tables],
    [t('delta.newTables'), change.newTables],
    [t('delta.files'), change.files],
  ]
  return (
    <li className="space-y-2 rounded-md border border-border px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-text">{change.name}</span>
        {change.stories.map((s) => (
          <Badge key={s} tone="brand">
            {s}
          </Badge>
        ))}
      </div>
      {change.description && <p className="text-text-2">{change.description}</p>}
      {change.endpoint && (
        <p className="font-mono text-xs text-text">
          {change.endpoint}
          {change.request.length > 0 && (
            <span className="block text-muted">
              {t('ivv.request')}: {change.request.map(fieldLabel).join(', ')}
            </span>
          )}
          {change.response.length > 0 && (
            <span className="block text-muted">
              {t('ivv.response')}: {change.response.map(fieldLabel).join(', ')}
            </span>
          )}
        </p>
      )}
      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[max-content_1fr]">
        {facts
          .filter(([, values]) => values.length > 0)
          .map(([label, values]) => (
            <div key={label} className="contents">
              <dt className="text-muted">{label}</dt>
              <dd className="font-mono text-text-2">{values.join(', ')}</dd>
            </div>
          ))}
      </dl>
    </li>
  )
}

function FilesCard({ projectId, added, changed }: { projectId: string; added: string[]; changed: string[] }) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('delta.deltaFiles')} subtitle={t('delta.deltaFilesHint')} />
      <CardBody className="grid gap-4 lg:grid-cols-2">
        <FileList projectId={projectId} title={t('delta.added')} files={added} tone="good" />
        <FileList projectId={projectId} title={t('delta.changed')} files={changed} tone="warning" />
      </CardBody>
    </Card>
  )
}

function FileList({
  projectId,
  title,
  files,
  tone,
}: {
  projectId: string
  title: string
  files: string[]
  tone: 'good' | 'warning'
}) {
  const { t } = useTranslation()
  return (
    <section className="space-y-2">
      <h4 className="flex items-center gap-2 text-sm font-semibold text-text">
        {title} <Badge tone={files.length > 0 ? tone : 'neutral'}>{files.length}</Badge>
      </h4>
      {files.length === 0 ? (
        <p className="text-xs text-muted">{t('ivv.none')}</p>
      ) : (
        <ul className="space-y-1 font-mono text-xs">
          {files.map((file) => (
            <li key={file}>
              <Link
                to="/projects/$projectId"
                params={{ projectId }}
                search={{ tab: 'code', file }}
                className="break-all text-brand underline-offset-2 hover:underline"
              >
                {file}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
