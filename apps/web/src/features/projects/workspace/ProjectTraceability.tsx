import { useMemo, useState } from 'react'
import { useSearch } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, CircleDashed, FileCode2, Loader2, Lock, XCircle } from 'lucide-react'
import { cn } from '@/lib/cn'
import { ApiError } from '@/api/client'
import type { ProjectDetail } from '@/api/projects'
import { CODE_VIEW, useRuleTrace, useTraceability, type TraceDetail } from '@/api/validation'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Input,
  Select,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'
import { VerdictBadge } from '@/components/ui/status'
import { Notice } from '../NewProjectWizard'
import { priorityTone, toRuleView } from './spec/model'
import { ListButton } from './spec/shared'
import { CodeExcerptView } from './validation/CodeExcerptView'
import {
  differencesOf,
  filterRules,
  stateCounts,
  toVerdict,
  traceState,
  traceTone,
  type TraceState,
} from './validation/model'

const STATES: TraceState[] = ['verified', 'notVerified', 'pending']
const stateIcon: Record<TraceState, typeof CheckCircle2> = {
  verified: CheckCircle2,
  notVerified: XCircle,
  pending: CircleDashed,
}

function StateBadge({ state }: { state: TraceState }) {
  const { t } = useTranslation()
  const Icon = stateIcon[state]
  return (
    <Badge tone={traceTone(state)}>
      <Icon size={12} aria-hidden /> {t(`traceability.state.${state}`)}
    </Badge>
  )
}

// Traceability tab, "Source ↔ target" (spec 11.6, 18.x), connected to the API: rule by rule, the legacy lines it was
// extracted from next to the generated files that implement it, and the behaviour of both sides in each golden or
// fresh case that exercises it. Showing code needs the code.view permission. Same look as the prototype's TraceabilityTab.
export function ProjectTraceability({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const canViewCode = project.permissions.includes(CODE_VIEW)
  const search = useSearch({ strict: false }) as { rule?: string }
  const rules = useTraceability(project.id, canViewCode)
  const [selected, setSelected] = useState<string | null>(search.rule ?? null)
  const [state, setState] = useState<'all' | TraceState>('all')
  const [query, setQuery] = useState('')
  const all = useMemo(() => rules.data ?? [], [rules.data])
  const list = useMemo(() => filterRules(all, state, query), [all, state, query])
  const current = list.find((r) => r.key === selected) ?? list[0] ?? null

  if (!canViewCode) {
    return (
      <EmptyState
        title={
          <span className="inline-flex items-center gap-2">
            <Lock size={16} className="text-muted" aria-hidden /> {t('traceability.noCodeView')}
          </span>
        }
        description={t('traceability.noCodeViewHint')}
      />
    )
  }
  if (rules.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('traceability.loading')}
      </p>
    )
  }
  if (rules.isError) {
    return (
      <EmptyState
        title={t('traceability.loadError')}
        description={rules.error instanceof ApiError ? rules.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void rules.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  if (all.length === 0) {
    return (
      <EmptyState
        title={t('traceability.emptyTitle')}
        description={t('traceability.emptyHint')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  const counts = stateCounts(all)

  return (
    <div className="space-y-4">
      <Notice tone="info">{t('traceability.intro')}</Notice>
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-56">
          <Input
            className="h-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('traceability.search')}
            aria-label={t('traceability.search')}
          />
        </div>
        <div className="w-48">
          <Select
            className="h-9"
            value={state}
            onChange={(e) => setState(e.target.value as 'all' | TraceState)}
            aria-label={t('traceability.filterState')}
          >
            <option value="all">{t('traceability.allStates')}</option>
            {STATES.map((s) => (
              <option key={s} value={s}>
                {t(`traceability.state.${s}`)} ({counts[s]})
              </option>
            ))}
          </Select>
        </div>
        <span className="text-sm text-muted">
          {t('traceability.summary', { count: all.length, verified: counts.verified })}
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="self-start">
          {list.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted">{t('traceability.noMatch')}</p>
          ) : (
            <ul className="divide-y divide-border" aria-label={t('traceability.rules')}>
              {list.map((r) => (
                <li key={r.key}>
                  <ListButton selected={current?.key === r.key} onClick={() => setSelected(r.key)}>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted">{r.key}</span>
                      {r.priority && <Badge tone={priorityTone(r.priority)}>{r.priority}</Badge>}
                      <span className="ml-auto">
                        <StateBadge state={traceState(r.verified)} />
                      </span>
                    </div>
                    <div className="mt-1 text-sm font-medium text-text">{r.name || r.key}</div>
                    <div className="text-xs text-muted">
                      {t('traceability.casesMatched', { matched: r.matched, count: r.cases })} ·{' '}
                      {t('traceability.targetFiles', { count: r.targetFiles.length })}
                    </div>
                  </ListButton>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {current && <RuleTraceView projectId={project.id} ruleKey={current.key} />}
      </div>
    </div>
  )
}

function RuleTraceView({ projectId, ruleKey }: { projectId: string; ruleKey: string }) {
  const { t } = useTranslation()
  const detail = useRuleTrace(projectId, ruleKey)
  if (detail.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('traceability.loadingRule')}
      </p>
    )
  }
  if (detail.isError || !detail.data) {
    return (
      <EmptyState
        title={t('traceability.loadError')}
        description={detail.error instanceof ApiError ? detail.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void detail.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  return <RuleTrace trace={detail.data} />
}

function RuleTrace({ trace }: { trace: TraceDetail }) {
  const { t } = useTranslation()
  const rule = toRuleView({
    key: trace.key,
    version: 0,
    status: trace.status,
    data: trace.rule,
    origin: '',
    createdAt: '',
  })
  const state = traceState(trace.verified)
  const differing = trace.cases.filter((c) => !c.matched).length

  return (
    <div className="min-w-0 space-y-4">
      <Card>
        <CardHeader
          title={
            <span>
              <span className="font-mono text-muted">{trace.key}</span> · {rule.name}
            </span>
          }
          subtitle={t('traceability.ruleHint')}
          action={
            <div className="flex flex-wrap justify-end gap-2">
              <StateBadge state={state} />
              {trace.verdict && <VerdictBadge verdict={toVerdict(trace.verdict)} />}
            </div>
          }
        />
        <CardBody className="space-y-3 text-sm">
          <div className="flex flex-wrap gap-2">
            {rule.priority && <Badge tone={priorityTone(rule.priority)}>{rule.priority}</Badge>}
            <Badge>{t(`spec.ruleStatus.${trace.status}`, { defaultValue: trace.status })}</Badge>
          </div>
          {rule.statement && <p className="text-text">{rule.statement}</p>}
          <p className="text-xs text-muted">{t(`traceability.stateHint.${state}`)}</p>
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="min-w-0 space-y-4" aria-label={t('traceability.legacy')}>
          {trace.legacy.length === 0 ? (
            <MissingCode title={t('traceability.legacy')} text={t('traceability.noLegacy')} />
          ) : (
            trace.legacy.map((e, i) => (
              <CodeExcerptView key={`${e.path}:${e.firstLine}:${i}`} title={t('traceability.legacy')} excerpt={e} />
            ))
          )}
        </section>
        <section className="min-w-0 space-y-4" aria-label={t('traceability.target')}>
          {trace.target.length === 0 ? (
            <MissingCode title={t('traceability.target')} text={t('traceability.noTarget')} />
          ) : (
            trace.target.map((e) => <CodeExcerptView key={e.path} title={t('traceability.target')} excerpt={e} />)
          )}
        </section>
      </div>

      <Card>
        <CardHeader
          title={t('traceability.outputs')}
          subtitle={t('traceability.behaviourHint')}
          action={
            trace.cases.length === 0 ? undefined : differing > 0 ? (
              <Badge tone="critical">
                <XCircle size={12} aria-hidden /> {t('traceability.differs', { count: differing })}
              </Badge>
            ) : (
              <Badge tone="good">
                <CheckCircle2 size={12} aria-hidden /> {t('traceability.allSame')}
              </Badge>
            )
          }
        />
        {trace.cases.length === 0 ? (
          <CardBody>
            <p className="text-sm text-muted">{t('traceability.noCases')}</p>
          </CardBody>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t('traceability.case')}</Th>
                <Th>{t('traceability.result')}</Th>
                <Th>{t('traceability.field')}</Th>
                <Th>{t('traceability.legacyValue')}</Th>
                <Th>{t('traceability.targetValue')}</Th>
              </tr>
            </thead>
            <tbody>
              {trace.cases.map((c) => {
                const diffs = differencesOf(c)
                const rows = Math.max(1, diffs.length)
                return Array.from({ length: rows }, (_, i) => (
                  <tr key={`${c.name}:${i}`} className={cn(!c.matched && 'bg-critical/5')}>
                    {i === 0 && (
                      <>
                        <Td className="align-top font-mono text-xs" rowSpan={rows}>
                          {c.name}
                        </Td>
                        <Td className="align-top" rowSpan={rows}>
                          {c.matched ? (
                            <Badge tone="good">
                              <CheckCircle2 size={12} aria-hidden /> {t('traceability.same')}
                            </Badge>
                          ) : (
                            <Badge tone="critical">
                              <XCircle size={12} aria-hidden /> {t('traceability.different')}
                            </Badge>
                          )}
                        </Td>
                      </>
                    )}
                    {diffs[i] ? (
                      <>
                        <Td className="font-mono text-xs break-all">{diffs[i].path}</Td>
                        <Td className="font-mono text-xs break-all text-text">{diffs[i].expected ?? '—'}</Td>
                        <Td className="font-mono text-xs break-all text-critical-ink">{diffs[i].actual ?? '—'}</Td>
                      </>
                    ) : (
                      <Td className="text-xs text-text-2" colSpan={3}>
                        {c.failure ?? (c.matched ? t('traceability.noDifferences') : '—')}
                      </Td>
                    )}
                  </tr>
                ))
              })}
            </tbody>
          </Table>
        )}
        {differing > 0 && (
          <CardBody>
            <Notice tone="warning">{t('traceability.differenceNote')}</Notice>
          </CardBody>
        )}
      </Card>
    </div>
  )
}

function MissingCode({ title, text }: { title: string; text: string }) {
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody className="flex items-center gap-2 text-sm text-muted">
        <FileCode2 size={16} aria-hidden /> {text}
      </CardBody>
    </Card>
  )
}
