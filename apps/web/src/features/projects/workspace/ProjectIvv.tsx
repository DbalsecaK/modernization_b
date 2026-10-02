import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, RotateCcw, Save } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import { ApiError } from '@/api/client'
import { IVV_EDIT_MAPPING, useIvv, useSaveIvvMapping, type IvvOut } from '@/api/ivv'
import type { ProjectDetail } from '@/api/projects'
import { Badge, Button, Card, CardBody, CardHeader, Code, EmptyState, Table, Td, Th } from '@/components/ui/primitives'
import { Textarea, toast } from '@/components/ui/overlay'
import { Notice } from '../NewProjectWizard'
import {
  comparisonOf,
  fieldLabel,
  inventoryOf,
  isDirty,
  mappingState,
  similarityLabel,
  sourceLabel,
  type RulePair,
  type TargetInventoryView,
} from './ivv/model'

// IV&V tab (Flow 4, ADR-0025), connected to the API: what the worker read of the third party's target, the interface
// mapping between the legacy's contract and the target's (a person corrects it before approving gate C2), the problems
// the server finds in it by code, the rule comparison and the report. The verdict is in the Validation tab.
export function ProjectIvv({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const ivv = useIvv(project.id)

  if (ivv.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('ivv.loading')}
      </p>
    )
  }
  if (ivv.isError) {
    return (
      <EmptyState
        title={t('ivv.loadError')}
        description={ivv.error instanceof ApiError ? ivv.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void ivv.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  const data = ivv.data
  if (!data || (data.inventory === null && data.mapping === null && data.report === null)) {
    return (
      <EmptyState
        title={t('ivv.emptyTitle')}
        description={t('ivv.notYet')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  const inventory = inventoryOf(data.inventory)
  const comparison = comparisonOf(data.comparison)

  return (
    <div className="space-y-6">
      {inventory && <InventoryCard inventory={inventory} />}
      {data.mapping !== null && (
        <MappingCard
          // A new saved version (here or by the intake) restarts the editor from the server's text.
          key={data.mappingUpdatedAt ?? ''}
          projectId={project.id}
          ivv={data}
          canEdit={project.permissions.includes(IVV_EDIT_MAPPING)}
        />
      )}
      {comparison && (
        <ComparisonCard present={comparison.present} missing={comparison.missing} extra={comparison.extra} />
      )}
      {data.report !== null && (
        <Card>
          <CardHeader title={t('ivv.report')} subtitle={t('ivv.reportHint')} />
          <CardBody>
            <Code label={t('ivv.report')} className="max-h-[32rem] whitespace-pre-wrap">
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
        title={t('ivv.inventory')}
        subtitle={t('ivv.inventoryHint')}
        action={<Badge tone="info">{inventory.stack}</Badge>}
      />
      {facts.length > 0 && <CardBody className="text-xs text-muted">{facts.join(' · ')}</CardBody>}
      <div className="border-t border-border px-5 pt-4 pb-2 text-sm font-semibold text-text">
        {t('ivv.endpoints', { count: inventory.endpoints.length })}
      </div>
      {inventory.endpoints.length === 0 ? (
        <CardBody className="text-sm text-muted">{t('ivv.noEndpoints')}</CardBody>
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
        <CardBody className="text-sm text-muted">{t('ivv.noTables')}</CardBody>
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

function MappingCard({ projectId, ivv, canEdit }: { projectId: string; ivv: IvvOut; canEdit: boolean }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(ivv.mapping ?? '')
  const [error, setError] = useState<string | null>(null)
  const save = useSaveIvvMapping(projectId, {
    onSuccess: (saved) => {
      setError(null)
      toast(
        saved.problems.length > 0 ? t('ivv.savedWithProblems', { count: saved.problems.length }) : t('ivv.savedReady'),
      )
    },
    // The API's problem detail explains it (an unreadable YAML, the wrong shape, no mapping yet).
    onError: (e) => setError(e instanceof ApiError ? e.message : t('common.error')),
  })
  const state = mappingState(ivv)
  const dirty = isDirty(draft, ivv.mapping)
  const submit = () => save.mutate(draft)

  return (
    <Card>
      <CardHeader
        title={t('ivv.mapping')}
        subtitle={
          ivv.mappingUpdatedAt
            ? t('ivv.mappingUpdated', { date: formatDateTime(ivv.mappingUpdatedAt) })
            : t('ivv.mappingHint')
        }
        action={
          <Badge tone={state === 'ready' ? 'good' : 'critical'}>
            {state === 'ready' ? t('ivv.readyBadge') : t('ivv.problemsBadge', { count: ivv.problems.length })}
          </Badge>
        }
      />
      <CardBody className="space-y-4">
        {state === 'ready' ? (
          <Notice tone="good">{t('ivv.readyForC2')}</Notice>
        ) : (
          <div className="space-y-2 rounded-md bg-critical/10 p-3 text-sm" role="alert">
            <p className="font-medium text-text">{t('ivv.problemsTitle', { count: ivv.problems.length })}</p>
            <ul className="list-disc space-y-1 pl-5 text-text-2">
              {ivv.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        )}
        {ivv.gaps.length > 0 && (
          <div className="space-y-2 rounded-md bg-warning/12 p-3 text-sm">
            <p className="font-medium text-text">{t('ivv.gapsTitle', { count: ivv.gaps.length })}</p>
            <p className="text-xs text-muted">{t('ivv.gapsHint')}</p>
            <ul className="list-disc space-y-1 pl-5 text-text-2">
              {ivv.gaps.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          </div>
        )}
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={18}
          spellCheck={false}
          readOnly={!canEdit}
          aria-label={t('ivv.mappingEditor')}
          className="font-mono text-xs leading-relaxed"
        />
        {error && <Notice tone="critical">{t('ivv.saveError', { detail: error })}</Notice>}
        {canEdit ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" disabled={!dirty || save.isPending} onClick={submit}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} {t('ivv.save')}
            </Button>
            <Button
              disabled={!dirty || save.isPending}
              onClick={() => {
                setDraft(ivv.mapping ?? '')
                setError(null)
              }}
            >
              <RotateCcw size={14} /> {t('ivv.discard')}
            </Button>
            <span className="text-xs text-muted">{t('ivv.saveHint')}</span>
          </div>
        ) : (
          <p className="text-xs text-muted">{t('ivv.noPermission')}</p>
        )}
      </CardBody>
    </Card>
  )
}

function ComparisonCard({ present, missing, extra }: { present: RulePair[]; missing: RulePair[]; extra: string[] }) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('ivv.comparison')} subtitle={t('ivv.comparisonHint')} />
      <CardBody className="grid gap-4 lg:grid-cols-3">
        <section className="space-y-2">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-text">
            {t('ivv.present')} <Badge tone="good">{present.length}</Badge>
          </h4>
          <PairList pairs={present} />
        </section>
        <section className="space-y-2">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-text">
            {t('ivv.missing')} <Badge tone={missing.length > 0 ? 'critical' : 'neutral'}>{missing.length}</Badge>
          </h4>
          <PairList pairs={missing} />
        </section>
        <section className="space-y-2">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-text">
            {t('ivv.extra')} <Badge tone={extra.length > 0 ? 'warning' : 'neutral'}>{extra.length}</Badge>
          </h4>
          {extra.length === 0 ? (
            <p className="text-xs text-muted">{t('ivv.none')}</p>
          ) : (
            <ul className="space-y-1 text-sm text-text-2">
              {extra.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          )}
        </section>
      </CardBody>
    </Card>
  )
}

function PairList({ pairs }: { pairs: RulePair[] }) {
  const { t } = useTranslation()
  if (pairs.length === 0) return <p className="text-xs text-muted">{t('ivv.none')}</p>
  return (
    <ul className="space-y-2 text-sm">
      {pairs.map((p) => (
        <li key={p.legacy || p.name} className="rounded-md border border-border px-3 py-2">
          <span className="block text-text">
            <span className="font-mono text-xs text-muted">{p.legacy}</span> {p.name}
          </span>
          {p.target && (
            <span className="block text-xs text-text-2">
              {t('ivv.inTarget', { name: p.target })}
              {p.similarity !== null && ` · ${t('ivv.similarity', { value: similarityLabel(p.similarity) })}`}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
