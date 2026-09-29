import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, FileText, History, MessageCircleQuestion } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import type { Question } from '@/api/runs'
import { useRuleVersions, type Coverage } from '@/api/spec'
import { Badge, Card, CardBody, CardHeader, Code, Input, Select, Table, Td, Th } from '@/components/ui/primitives'
import { Notice } from '../../NewProjectWizard'
import { citation, priorityTone, ruleStatusTone, type DataItem, type RuleView } from './model'
import { ListButton } from './shared'

const RULE_STATUSES = ['draft', 'review', 'approved', 'reopened', 'obsolete'] as const

// Business rules extracted from the legacy (spec 4.1): statement, Gherkin scenarios with concrete values, file:line
// citations, confidence, the question for the SME and suspected defects. Read-only: people confirm them through the
// questions and gate C1.
export function RulesView({
  projectId,
  rules,
  coverage,
  questions,
  onOpenStory,
}: {
  projectId: string
  rules: RuleView[]
  coverage: Coverage | undefined
  questions: Question[]
  onOpenStory: (key: string) => void
}) {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<string | null>(null)
  const [status, setStatus] = useState<'all' | string>('all')
  const [priority, setPriority] = useState<'all' | string>('all')
  const [query, setQuery] = useState('')
  const list = useMemo(
    () =>
      rules.filter(
        (r) =>
          (status === 'all' || r.status === status) &&
          (priority === 'all' || r.priority === priority) &&
          `${r.key} ${r.name} ${r.domain}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [rules, status, priority, query],
  )
  const rule = rules.find((r) => r.key === selected) ?? list[0] ?? null
  const openAbout = (key: string) => questions.filter((q) => q.status === 'open' && q.affects.includes(key))
  const p0 = rules.filter((r) => r.priority === 'P0').length

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-56">
          <Input
            className="h-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('spec.search')}
            aria-label={t('spec.search')}
          />
        </div>
        <div className="w-44">
          <Select
            className="h-9"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label={t('spec.filterStatus')}
          >
            <option value="all">{t('spec.allStatuses')}</option>
            {RULE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`spec.ruleStatus.${s}`)}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-40">
          <Select
            className="h-9"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            aria-label={t('spec.filterPriority')}
          >
            <option value="all">{t('spec.allPriorities')}</option>
            {['P0', 'P1', 'P2'].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        </div>
        <span className="text-sm text-muted">
          {t('spec.rulesTotal', { count: rules.length })} · P0: {p0}
          {coverage &&
            ` · ${t('stories.coverageSummary', { covered: Object.keys(coverage.covered).length, elements: coverage.elements })}`}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card>
          {list.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted">{t('spec.noRuleMatch')}</p>
          ) : (
            <ul className="divide-y divide-border" aria-label={t('spec.views.rules')}>
              {list.map((r) => (
                <li key={r.key}>
                  <ListButton selected={rule?.key === r.key} onClick={() => setSelected(r.key)}>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted">{r.key}</span>
                      <Badge tone={priorityTone(r.priority)}>{r.priority}</Badge>
                      {openAbout(r.key).length > 0 && (
                        <MessageCircleQuestion
                          size={12}
                          className="text-warning"
                          aria-label={t('spec.openQuestions', { count: openAbout(r.key).length })}
                        />
                      )}
                      {r.suspectedDefect && (
                        <AlertTriangle size={12} className="text-critical" aria-label={t('spec.suspectedDefect')} />
                      )}
                      <Badge tone={ruleStatusTone(r.status)} className="ml-auto">
                        {t(`spec.ruleStatus.${r.status}`, { defaultValue: r.status })}
                      </Badge>
                    </div>
                    <div className="mt-1 text-sm font-medium text-text">{r.name}</div>
                    <div className="text-xs text-muted">
                      {[r.domain, r.category && t(`ruleCategory.${r.category}`, { defaultValue: r.category })]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                  </ListButton>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {rule && (
          <RuleDetail
            projectId={projectId}
            rule={rule}
            coveredBy={coverage?.covered[rule.key] ?? []}
            outOfScope={coverage?.outOfScope.includes(rule.key) ?? false}
            openQuestions={openAbout(rule.key)}
            onOpenStory={onOpenStory}
          />
        )}
      </div>
    </div>
  )
}

function RuleDetail({
  projectId,
  rule,
  coveredBy,
  outOfScope,
  openQuestions,
  onOpenStory,
}: {
  projectId: string
  rule: RuleView
  coveredBy: string[]
  outOfScope: boolean
  openQuestions: Question[]
  onOpenStory: (key: string) => void
}) {
  const { t } = useTranslation()
  const versions = useRuleVersions(projectId, rule.key)
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={
            <span>
              <span className="font-mono text-muted">{rule.key}</span> · {rule.name}
            </span>
          }
          subtitle={t('spec.confidence', {
            level: t(`confidence.${rule.confidence}`, { defaultValue: rule.confidence }),
          })}
        />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge tone={priorityTone(rule.priority)}>{rule.priority}</Badge>
            {rule.category && <Badge>{t(`ruleCategory.${rule.category}`, { defaultValue: rule.category })}</Badge>}
            {rule.domain && <Badge tone="info">{rule.domain}</Badge>}
            <Badge tone={ruleStatusTone(rule.status)}>
              {t(`spec.ruleStatus.${rule.status}`, { defaultValue: rule.status })}
            </Badge>
          </div>
          <p className="text-sm text-text">{rule.statement}</p>
          {(rule.condition || rule.action) && (
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              {rule.condition && (
                <div>
                  <dt className="text-xs text-muted">{t('spec.condition')}</dt>
                  <dd className="text-text">{rule.condition}</dd>
                </div>
              )}
              {rule.action && (
                <div>
                  <dt className="text-xs text-muted">{t('spec.action')}</dt>
                  <dd className="text-text">{rule.action}</dd>
                </div>
              )}
            </dl>
          )}

          <div>
            <div className="mb-1 text-xs font-medium text-muted">{t('spec.scenarios')}</div>
            {rule.scenarios.length === 0 ? (
              <span className="text-xs text-muted">{t('spec.noScenarios')}</span>
            ) : (
              <div className="space-y-2">
                {rule.scenarios.map((s, i) => (
                  <Code key={i} className="whitespace-pre-wrap">
                    {s}
                  </Code>
                ))}
              </div>
            )}
          </div>

          {(rule.inputs.length > 0 || rule.outputs.length > 0) && (
            <div className="grid gap-3 sm:grid-cols-2">
              <DataItems label={t('spec.inputs')} items={rule.inputs} />
              <DataItems label={t('spec.outputs')} items={rule.outputs} />
            </div>
          )}

          <div>
            <div className="mb-1 text-xs font-medium text-muted">{t('spec.citations')}</div>
            <ul className="flex flex-wrap gap-2">
              {rule.sources.map((s, i) => (
                <li
                  key={i}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 font-mono text-xs text-text-2"
                >
                  <FileText size={12} /> {citation(s)}
                </li>
              ))}
            </ul>
          </div>

          {rule.hardcoded.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium text-muted">{t('spec.hardcoded')}</div>
              <div className="flex flex-wrap gap-1">
                {rule.hardcoded.map((h) => (
                  <span key={h} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text">
                    {h}
                  </span>
                ))}
              </div>
            </div>
          )}

          {rule.suspectedDefect && (
            <Notice tone="critical">
              <strong>{t('spec.suspectedDefect')}:</strong> {rule.suspectedDefect}
            </Notice>
          )}
          {rule.smeQuestion && (
            <Notice tone="warning">
              <strong>{t('spec.smeQuestion')}:</strong> {rule.smeQuestion}
            </Notice>
          )}
          {openQuestions.length > 0 && (
            <Notice tone="warning">{t('spec.openQuestions', { count: openQuestions.length })}</Notice>
          )}

          <div className="border-t border-border pt-3 text-sm">
            <div className="mb-1 text-xs font-medium text-muted">{t('spec.coveredBy')}</div>
            {coveredBy.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {coveredBy.map((k) => (
                  <button
                    key={k}
                    className="font-mono text-xs text-info-ink hover:underline"
                    onClick={() => onOpenStory(k)}
                  >
                    {k}
                  </button>
                ))}
              </div>
            ) : (
              <span className="text-xs text-muted">{outOfScope ? t('spec.ruleOutOfScope') : t('spec.notCovered')}</span>
            )}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-1.5">
              <History size={14} /> {t('spec.versions')}
            </span>
          }
        />
        <ul className="divide-y divide-border">
          {(versions.data ?? []).map((v) => (
            <li key={v.version} className="flex flex-wrap items-center gap-x-2 px-5 py-2 text-xs">
              <span className="font-mono text-muted">v{v.version}</span>
              <span className="text-muted tabular">{formatDateTime(v.createdAt)}</span>
              <Badge tone={ruleStatusTone(v.status)}>
                {t(`spec.ruleStatus.${v.status}`, { defaultValue: v.status })}
              </Badge>
              <span className="text-text-2">{t(`spec.origin.${v.origin}`, { defaultValue: v.origin })}</span>
            </li>
          ))}
          {versions.isLoading && <li className="px-5 py-3 text-xs text-muted">{t('common.loading')}</li>}
        </ul>
      </Card>
    </div>
  )
}

function DataItems({ label, items }: { label: string; items: DataItem[] }) {
  const { t } = useTranslation()
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted">{label}</div>
      {items.length === 0 ? (
        <span className="text-xs text-muted">—</span>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('spec.field')}</Th>
              <Th>{t('spec.type')}</Th>
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr key={d.name} title={d.description || undefined}>
                <Td className="font-mono text-xs">{d.name}</Td>
                <Td className="font-mono text-xs">{d.type}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  )
}
