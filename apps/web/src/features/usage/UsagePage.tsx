import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Pencil, Plus, Table2, Trash2 } from 'lucide-react'
import { formatCompact, formatCost, formatDay, formatNumber, formatUsd } from '@/lib/format'
import { can, useMe } from '@/api/session'
import { useBudgets, useDeleteBudget, usd, useUsage, type Budget, type GroupBy, type UsageRow } from '@/api/ai'
import { toast } from '@/components/ui/overlay'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  PageHeader,
  Progress,
  Select,
  StatTile,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'
import { BarList, LineChart } from '@/components/charts/charts'
import { useCatalog } from '@/api/projects'
import { agentName } from '@/features/catalog/AgentCard'
import { errorMessage } from '@/features/admin/AdminForms'
import { Notice } from '@/features/projects/NewProjectWizard'
import { BudgetForm } from './BudgetForm'

const RANGES = ['monthToDate', 'last30', 'last90'] as const
type Range = (typeof RANGES)[number]
const BREAKDOWNS: GroupBy[] = ['project', 'model', 'phase', 'agentRole', 'provider']

// Calendar days of the user (the ledger is summarized by UTC day; a few hours of difference at the edges).
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function dateRange(range: Range): { since: string; until: string } {
  const today = new Date()
  const until = iso(today)
  if (range === 'monthToDate') return { since: `${until.slice(0, 8)}01`, until }
  const since = new Date(today)
  since.setDate(since.getDate() - (range === 'last30' ? 29 : 89))
  return { since: iso(since), until }
}

const tokens = (r: UsageRow) => r.inputTokens + r.outputTokens

export function UsagePage() {
  const { t } = useTranslation()
  const me = useMe()
  const [range, setRange] = useState<Range>('monthToDate')
  const [breakdown, setBreakdown] = useState<GroupBy>('project')
  const { since, until } = dateRange(range)
  const daily = useUsage('day', since, until)
  const byProject = useUsage('project', since, until)
  const byModel = useUsage('model', since, until)
  const detail = useUsage(breakdown, since, until)
  const costVisible = !!daily.data?.costVisible
  const total = daily.data?.total
  // Money when the user may see it (cost.view); tokens otherwise (spec 13.5).
  const measure = (r: UsageRow) => (costVisible ? (usd(r.costUsd) ?? 0) : tokens(r))
  const format = (v: number) => (costVisible ? formatCost(v) : formatCompact(v))
  const label = useGroupLabel()

  if (!me?.activeTenant) return <Notice tone="info">{t('admin.noActiveTenant')}</Notice>

  return (
    <>
      <PageHeader
        title={t('usage.title')}
        description={t('usage.description')}
        actions={
          <>
            <Select
              className="w-44"
              value={range}
              onChange={(e) => setRange(e.target.value as Range)}
              aria-label={t('usage.range')}
            >
              {RANGES.map((r) => (
                <option key={r} value={r}>
                  {t(`usage.${r}`)}
                </option>
              ))}
            </Select>
            <Button
              disabled={!detail.data}
              onClick={() => detail.data && exportCsv(detail.data.rows, breakdown, since)}
            >
              <Download size={16} /> {t('usage.export')}
            </Button>
          </>
        }
      />
      <div className="space-y-6">
        {daily.data && !costVisible && <Notice tone="info">{t('usage.costHidden')}</Notice>}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label={t('usage.spend')}
            value={costVisible && total ? formatCost(usd(total.costUsd) ?? 0) : '—'}
            hint={t('usage.rangeHint', { since: formatDay(since), until: formatDay(until) })}
          />
          <StatTile label={t('usage.tokens')} value={total ? formatCompact(tokens(total)) : '—'} />
          <StatTile label={t('usage.calls')} value={total ? formatNumber(total.calls) : '—'} />
          <StatTile
            label={t('usage.failedCalls')}
            value={total ? formatNumber(total.failedCalls) : '—'}
            hint={t('usage.failedHint')}
          />
        </div>
        <Trend rows={daily.data?.rows ?? []} measure={measure} format={format} costVisible={costVisible} />
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader title={t('usage.byProject')} />
            <CardBody>
              <Bars
                rows={byProject.data?.rows ?? []}
                label={(r) => label('project', r)}
                measure={measure}
                format={format}
              />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t('usage.byModel')} />
            <CardBody>
              <Bars
                rows={byModel.data?.rows ?? []}
                label={(r) => label('model', r)}
                measure={measure}
                format={format}
              />
            </CardBody>
          </Card>
        </div>
        <Card>
          <CardHeader
            title={t('usage.breakdown')}
            action={
              <Select
                className="h-9 w-48"
                value={breakdown}
                onChange={(e) => setBreakdown(e.target.value as GroupBy)}
                aria-label={t('usage.groupBy')}
              >
                {BREAKDOWNS.map((g) => (
                  <option key={g} value={g}>
                    {t(`usage.groups.${g}`)}
                  </option>
                ))}
              </Select>
            }
          />
          <Table>
            <thead>
              <tr>
                <Th>{t(`usage.groups.${breakdown}`)}</Th>
                <Th className="text-right">{t('usage.calls')}</Th>
                <Th className="text-right">{t('usage.inputTokens')}</Th>
                <Th className="text-right">{t('usage.outputTokens')}</Th>
                <Th className="text-right">{t('usage.reasoningTokens')}</Th>
                <Th className="text-right">{t('usage.cacheReadTokens')}</Th>
                {costVisible && <Th className="text-right">{t('usage.cost')}</Th>}
              </tr>
            </thead>
            <tbody>
              {(detail.data?.rows ?? []).map((r) => (
                <tr key={r.key ?? 'none'}>
                  <Td className="text-text">{label(breakdown, r)}</Td>
                  <Td className="text-right tabular">{formatNumber(r.calls)}</Td>
                  <Td className="text-right tabular">{formatNumber(r.inputTokens)}</Td>
                  <Td className="text-right tabular">{formatNumber(r.outputTokens)}</Td>
                  <Td className="text-right tabular">{formatNumber(r.reasoningTokens)}</Td>
                  <Td className="text-right tabular">{formatNumber(r.cacheReadTokens)}</Td>
                  {costVisible && <Td className="text-right tabular">{formatCost(usd(r.costUsd) ?? 0)}</Td>}
                </tr>
              ))}
            </tbody>
          </Table>
          {detail.data?.rows.length === 0 && (
            <CardBody>
              <p className="text-sm text-muted">{t('usage.noUsage')}</p>
            </CardBody>
          )}
        </Card>
        {can(me, 'cost.view') && <Budgets canEdit={can(me, 'models.configure')} />}
        <Notice tone="info">{t('usage.ledgerNote')}</Notice>
      </div>
    </>
  )
}

/** Labels of the grouping keys: phases and agent roles are translated, the rest come from the ledger. */
function useGroupLabel() {
  const { t, i18n } = useTranslation()
  const agents = useCatalog().data?.agents ?? []
  return (group: GroupBy, r: UsageRow) => {
    if (r.key == null) return t('usage.unassigned')
    if (group === 'phase') return r.key === 'connection-test' ? t('usage.connectionTest') : t(`phases.${r.key}`)
    if (group === 'agentRole') {
      const agent = agents.find((a) => a.key === r.key)
      return agent ? agentName(agent, i18n.language) : r.key
    }
    return r.label
  }
}

function Trend({
  rows,
  measure,
  format,
  costVisible,
}: {
  rows: UsageRow[]
  measure: (r: UsageRow) => number
  format: (v: number) => string
  costVisible: boolean
}) {
  const { t } = useTranslation()
  const [showTable, setShowTable] = useState(false)
  const points = [...rows].sort((a, b) => (a.key ?? '').localeCompare(b.key ?? ''))
  const title = costVisible ? t('usage.trend') : t('usage.trendTokens')
  return (
    <Card>
      <CardHeader
        title={title}
        action={
          <Button size="sm" variant="ghost" onClick={() => setShowTable((v) => !v)} aria-pressed={showTable}>
            <Table2 size={14} /> {showTable ? t('usage.showChart') : t('usage.showTable')}
          </Button>
        }
      />
      <CardBody>
        {points.length === 0 ? (
          <EmptyState title={t('usage.noUsage')} description={t('usage.noUsageHint')} />
        ) : showTable ? (
          <Table>
            <thead>
              <tr>
                <Th>{t('usage.day')}</Th>
                <Th className="text-right">{costVisible ? t('usage.cost') : t('usage.tokens')}</Th>
              </tr>
            </thead>
            <tbody>
              {points.map((r) => (
                <tr key={r.key}>
                  <Td>{formatDay(r.key ?? '')}</Td>
                  <Td className="text-right tabular">{format(measure(r))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <LineChart
            data={points.map((r) => ({ x: formatDay(r.key ?? ''), y: measure(r) }))}
            format={format}
            label={title}
          />
        )}
      </CardBody>
    </Card>
  )
}

function Bars({
  rows,
  label,
  measure,
  format,
}: {
  rows: UsageRow[]
  label: (r: UsageRow) => string
  measure: (r: UsageRow) => number
  format: (v: number) => string
}) {
  const { t } = useTranslation()
  if (rows.length === 0) return <p className="text-sm text-muted">{t('usage.noUsage')}</p>
  return <BarList data={rows.slice(0, 8).map((r) => ({ label: label(r), value: measure(r) }))} format={format} />
}

function Budgets({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation()
  const budgets = useBudgets(true)
  const remove = useDeleteBudget()
  const [form, setForm] = useState<{ open: boolean; initial?: Budget; key: number }>({ open: false, key: 0 })
  const open = (initial?: Budget) => setForm((f) => ({ open: true, initial, key: f.key + 1 }))
  return (
    <Card>
      <BudgetForm
        key={form.key}
        open={form.open}
        initial={form.initial}
        onClose={() => setForm((f) => ({ ...f, open: false }))}
      />
      <CardHeader
        title={t('usage.budgets')}
        subtitle={t('usage.budgetsHint')}
        action={
          canEdit && (
            <Button size="sm" onClick={() => open()}>
              <Plus size={14} /> {t('usage.newBudget')}
            </Button>
          )
        }
      />
      {budgets.data?.length === 0 ? (
        <CardBody>
          <p className="text-sm text-muted">{t('usage.noBudgets')}</p>
        </CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('usage.scope')}</Th>
              <Th>{t('usage.period')}</Th>
              <Th>{t('usage.consumed')}</Th>
              <Th className="text-right">{t('usage.spentOfBudget')}</Th>
              <Th>{t('usage.alerts')}</Th>
              {canEdit && <Th />}
            </tr>
          </thead>
          <tbody>
            {(budgets.data ?? []).map((b) => {
              const spent = usd(b.spentUsd) ?? 0
              const amount = usd(b.amountUsd) ?? 0
              const pct = amount ? Math.round((spent / amount) * 100) : 0
              const scope = b.projectName ?? t('ai.wholeTenant')
              return (
                <tr key={b.id}>
                  <Td className="text-text">{scope}</Td>
                  <Td>
                    {t(`usage.periods.${b.period}`)}
                    {b.period === 'monthly' && <div className="text-xs text-muted">{b.periodKey}</div>}
                  </Td>
                  <Td className="w-56">
                    <Progress
                      label={t('usage.consumedOf', { scope })}
                      value={Math.min(pct, 100)}
                      tone={pct >= 100 ? 'critical' : pct >= b.alertPct ? 'warning' : 'brand'}
                    />
                    <div className="mt-1 text-xs text-muted tabular">{pct}%</div>
                  </Td>
                  <Td className="text-right tabular">
                    {formatCost(spent)} / {formatUsd(amount, 2)}
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {b.alerts.map((level) => (
                        <Badge key={level} tone={level >= 100 ? 'critical' : 'warning'}>
                          {t('usage.alertReached', { level })}
                        </Badge>
                      ))}
                      <Badge>{b.hardStop ? t('usage.stopsAt100') : t('usage.alertsOnly', { pct: b.alertPct })}</Badge>
                    </div>
                  </Td>
                  {canEdit && (
                    <Td className="whitespace-nowrap text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('usage.editBudgetOf', { scope })}
                        onClick={() => open(b)}
                      >
                        <Pencil size={14} />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('usage.deleteBudgetOf', { scope })}
                        onClick={async () => {
                          if (!window.confirm(t('usage.confirmDeleteBudget', { scope }))) return
                          try {
                            await remove.mutateAsync(b.id)
                            toast(t('usage.budgetDeleted'))
                          } catch (error) {
                            toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
                          }
                        }}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </Td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function exportCsv(rows: UsageRow[], group: GroupBy, since: string) {
  const header = [
    'key',
    'label',
    'calls',
    'failed_calls',
    'input_tokens',
    'output_tokens',
    'reasoning_tokens',
    'cache_read_tokens',
    'cost_usd',
  ]
  const quote = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`
  const lines = rows.map((r) =>
    [
      r.key,
      r.label,
      r.calls,
      r.failedCalls,
      r.inputTokens,
      r.outputTokens,
      r.reasoningTokens,
      r.cacheReadTokens,
      r.costUsd ?? '',
    ]
      .map(quote)
      .join(','),
  )
  const blob = new Blob([[header.join(','), ...lines].join('\n')], { type: 'text/csv' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `usage-${group}-${since}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}
