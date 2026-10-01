import { useTranslation } from 'react-i18next'
import { Loader2, Lock } from 'lucide-react'
import { formatCompact, formatCost, formatNumber } from '@/lib/format'
import { ApiError } from '@/api/client'
import { USAGE_VIEW, usd, useProjectUsage, type UsageRow } from '@/api/ai'
import { useCatalog, type ProjectDetail } from '@/api/projects'
import { BarList } from '@/components/charts/charts'
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Progress,
  StatTile,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'
import { agentName } from '@/features/catalog/AgentCard'
import { Notice } from '../NewProjectWizard'

const tokens = (r: UsageRow) => r.inputTokens + r.outputTokens

// Costs tab (spec 13.5 "Por proyecto", 18.3), connected to the API: what the project consumed over its whole life
// by phase, agent and model against its budget, and what the self-correction retries cost. Without cost.view the
// same view shows tokens and no money. Same look as the prototype's CostsTab.
export function ProjectCosts({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t, i18n } = useTranslation()
  const allowed = project.permissions.includes(USAGE_VIEW)
  const usage = useProjectUsage(project.id, allowed)
  const agents = useCatalog().data?.agents ?? []

  if (!allowed) {
    return (
      <EmptyState
        title={
          <span className="inline-flex items-center gap-2">
            <Lock size={16} className="text-muted" aria-hidden /> {t('projectCosts.noUsageView')}
          </span>
        }
        description={t('projectCosts.noUsageViewHint')}
      />
    )
  }
  if (usage.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('projectCosts.loading')}
      </p>
    )
  }
  if (usage.isError || !usage.data) {
    return (
      <EmptyState
        title={t('projectCosts.loadError')}
        description={usage.error instanceof ApiError ? usage.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void usage.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  const u = usage.data
  if (u.total.calls + u.total.failedCalls === 0) {
    return (
      <EmptyState
        title={t('project.later.costs')}
        description={t('projectCosts.emptyHint')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  const money = u.costVisible
  const spent = usd(u.total.costUsd) ?? 0
  const budget = usd(u.budgetUsd)
  const pct = budget ? Math.round((spent / budget) * 100) : null
  const retries = usd(u.selfCorrection.costUsd) ?? 0
  const measure = (r: UsageRow) => (money ? (usd(r.costUsd) ?? 0) : tokens(r))
  const format = (v: number) => (money ? formatCost(v) : formatCompact(v))
  const phaseLabel = (r: UsageRow) => (r.key ? t(`phases.${r.key}`, { defaultValue: r.key }) : t('usage.unassigned'))
  const agentLabel = (r: UsageRow) => {
    const agent = agents.find((a) => a.key === r.key)
    return agent ? agentName(agent, i18n.language) : (r.key ?? t('usage.unassigned'))
  }

  return (
    <div className="space-y-6">
      {!money && <Notice tone="info">{t('projectCosts.tokensOnly')}</Notice>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label={t('costs.spent')}
          value={money ? formatCost(spent) : '—'}
          hint={
            pct != null ? (
              <Progress
                value={Math.min(pct, 100)}
                tone={pct >= 80 ? 'warning' : 'brand'}
                label={t('costs.used', { pct })}
              />
            ) : undefined
          }
        />
        <StatTile
          label={t('costs.budget')}
          value={money && budget ? formatCost(budget) : '—'}
          hint={pct != null ? t('costs.used', { pct }) : money ? t('projectCosts.noBudget') : undefined}
        />
        <StatTile
          label={t('costs.tokens')}
          value={formatCompact(tokens(u.total))}
          hint={t('projectCosts.calls', { count: u.total.calls })}
        />
        <StatTile
          label={t('projectCosts.selfCorrection')}
          value={money ? formatCost(retries) : formatCompact(tokens(u.selfCorrection))}
          hint={t('projectCosts.calls', { count: u.selfCorrection.calls })}
        />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={money ? t('costs.byPhase') : t('projectCosts.tokensByPhase')} />
          <CardBody>
            <BarList data={u.byPhase.map((r) => ({ label: phaseLabel(r), value: measure(r) }))} format={format} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={money ? t('costs.byAgent') : t('projectCosts.tokensByAgent')} />
          <CardBody>
            <BarList data={u.byAgent.map((r) => ({ label: agentLabel(r), value: measure(r) }))} format={format} />
          </CardBody>
        </Card>
      </div>
      <Card>
        <CardHeader title={t('projectCosts.byModel')} />
        <Table>
          <thead>
            <tr>
              <Th>{t('projectCosts.model')}</Th>
              <Th className="text-right">{t('usage.calls')}</Th>
              <Th className="text-right">{t('projectCosts.inputTokens')}</Th>
              <Th className="text-right">{t('projectCosts.outputTokens')}</Th>
              {money && <Th className="text-right">{t('projectCosts.cost')}</Th>}
            </tr>
          </thead>
          <tbody>
            {u.byModel.map((r) => (
              <tr key={r.key ?? '—'}>
                <Td className="font-mono text-xs">{r.label}</Td>
                <Td className="text-right tabular">{formatNumber(r.calls)}</Td>
                <Td className="text-right tabular">{formatNumber(r.inputTokens)}</Td>
                <Td className="text-right tabular">{formatNumber(r.outputTokens)}</Td>
                {money && <Td className="text-right tabular">{formatCost(usd(r.costUsd) ?? 0)}</Td>}
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {money && spent > 0 && (
        <Notice tone="info">
          {t('costs.selfCorrectionShare', { usd: formatCost(retries), pct: Math.round((retries / spent) * 100) })}
        </Notice>
      )}
    </div>
  )
}
