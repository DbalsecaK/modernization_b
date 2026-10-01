import { useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ArrowRight, Loader2, PauseCircle, PlugZap, ShieldAlert, Siren } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatCompact, formatCost, formatDateTime, formatMonth, formatNumber } from '@/lib/format'
import { ApiError } from '@/api/client'
import { useDashboard, type Dashboard } from '@/api/dashboard'
import { useActivityStream, useTasks } from '@/api/runs'
import { useMe } from '@/api/session'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  PageHeader,
  Progress,
  StatTile,
} from '@/components/ui/primitives'
import { PhaseStatusIcon, VerdictBadge } from '@/components/ui/status'
import { BarList, LineChart } from '@/components/charts/charts'
import { toVerdict } from '@/features/projects/workspace/validation/model'
import { adminAlerts, progressOf, risks, runPhaseStatus, totals, type Risk } from './model'

type Perspective = 'executive' | 'delivery' | 'admin'

/** Rows a list shows before saying how many more there are (the full lists live in Projects and My tasks). */
const SHOWN = 8

const amount = (value: string | null | undefined) => (value == null ? 0 : Number(value))

// Dashboard by profile (spec 18.2), connected to the API: the executive view of progress, verification and spend;
// the delivery view of runs, gates, escalations and live activity; and the administrator's users, connections and
// alerts. Same look as the prototype.
export function DashboardPage() {
  const { t } = useTranslation()
  const me = useMe()
  const [perspective, setPerspective] = useState<Perspective>('executive')
  const board = useDashboard(!!me?.activeTenant)

  return (
    <>
      <PageHeader
        title={t('dashboard.title')}
        description={t('dashboard.description')}
        actions={
          <div
            className="flex rounded-md border border-border bg-surface p-0.5 text-sm"
            role="group"
            aria-label={t('dashboard.perspective')}
          >
            {(['executive', 'delivery', 'admin'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPerspective(p)}
                aria-pressed={perspective === p}
                className={cn(
                  'rounded px-3 py-1.5',
                  perspective === p ? 'bg-brand text-brand-contrast' : 'text-text-2 hover:text-text',
                )}
              >
                {t(`dashboard.perspectives.${p}`)}
              </button>
            ))}
          </div>
        }
      />
      {!me?.activeTenant ? (
        <EmptyState title={t('dashboard.noTenant')} description={t('dashboard.noTenantHint')} />
      ) : board.isLoading ? (
        <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
          <Loader2 size={16} className="animate-spin" /> {t('dashboard.loading')}
        </p>
      ) : board.isError || !board.data ? (
        <EmptyState
          title={t('dashboard.loadError')}
          description={board.error instanceof ApiError ? board.error.message : undefined}
          action={
            <Button size="sm" onClick={() => void board.refetch()}>
              {t('spec.retry')}
            </Button>
          }
        />
      ) : (
        <>
          {perspective === 'executive' && <ExecutiveView board={board.data} />}
          {perspective === 'delivery' && <DeliveryView board={board.data} />}
          {perspective === 'admin' && <AdminView board={board.data} tenants={me.tenants.length} />}
        </>
      )}
    </>
  )
}

function ExecutiveView({ board }: { board: Dashboard }) {
  const { t } = useTranslation()
  const sum = totals(board)
  const found = risks(board)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label={t('dashboard.activeProjects')}
          value={sum.active}
          hint={t('dashboard.ofTotal', { total: board.projects.length })}
        />
        <StatTile
          label={t('dashboard.rulesVerified')}
          value={`${sum.rulesVerified} / ${sum.rulesTotal}`}
          hint={t('dashboard.rulesVerifiedHint')}
        />
        <StatTile label={t('dashboard.provenModules')} value={sum.proven} hint={t('dashboard.provenHint')} />
        <StatTile
          label={t('dashboard.spendVsBudget')}
          value={sum.spent != null ? formatCost(sum.spent) : '—'}
          hint={
            sum.spent == null
              ? t('dashboard.needsCostView')
              : sum.budget
                ? t('dashboard.budgetOf', { budget: formatCost(sum.budget) })
                : undefined
          }
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title={t('dashboard.projectProgress')}
            action={
              <Link to="/projects" className="text-sm font-medium text-brand hover:underline">
                {t('common.viewAll')}
              </Link>
            }
          />
          <CardBody className="divide-y divide-border p-0">
            {board.projects.length === 0 && <p className="px-5 py-4 text-sm text-muted">{t('dashboard.noProjects')}</p>}
            {board.projects.slice(0, SHOWN).map((p) => {
              const pct = progressOf(p)
              return (
                <Link
                  key={p.id}
                  to="/projects/$projectId"
                  params={{ projectId: p.id }}
                  className="flex items-center gap-4 px-5 py-3 hover:bg-surface-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text">{p.name}</div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted">
                      <PhaseStatusIcon status={runPhaseStatus(p.runStatus)} size={12} />
                      {p.currentPhase
                        ? t(`phases.${p.currentPhase}`, { defaultValue: p.currentPhase })
                        : t('dashboard.notStarted')}
                    </div>
                  </div>
                  <div className="hidden w-40 shrink-0 sm:block">
                    <Progress value={pct} label={t('dashboard.progressOf', { project: p.name })} />
                    <div className="mt-1 text-right text-xs text-muted tabular">{pct}%</div>
                  </div>
                  <div className="flex w-32 shrink-0 justify-end">
                    <VerdictBadge verdict={toVerdict(p.verdict)} />
                  </div>
                </Link>
              )
            })}
            {board.projects.length > SHOWN && (
              <p className="px-5 py-3 text-xs text-muted">
                {t('dashboard.more', { count: board.projects.length - SHOWN })}
              </p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('dashboard.risks')} />
          <CardBody className="space-y-3">
            {found.length === 0 && <p className="text-sm text-muted">{t('dashboard.noRisks')}</p>}
            {found.slice(0, SHOWN).map((r, i) => (
              <RiskLine key={i} risk={r} />
            ))}
            {found.length > SHOWN && (
              <p className="text-xs text-muted">{t('dashboard.more', { count: found.length - SHOWN })}</p>
            )}
          </CardBody>
        </Card>
      </div>
      {board.costVisible && (
        <Card>
          <CardHeader title={t('dashboard.monthlySpend')} subtitle={t('dashboard.monthlySpendHint')} />
          <CardBody>
            {board.monthlySpend.length > 0 ? (
              <LineChart
                data={board.monthlySpend.map((m) => ({ x: formatMonth(m.month), y: amount(m.usd) }))}
                format={(v) => formatCost(v)}
                label={t('dashboard.monthlySpend')}
              />
            ) : (
              <p className="text-sm text-muted">{t('dashboard.noSpend')}</p>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  )
}

function RiskLine({ risk }: { risk: Risk }) {
  const { t } = useTranslation()
  if (risk.kind === 'escalation')
    return <Line icon={<Siren size={16} className="text-critical" />} text={t('dashboard.riskEscalation', risk)} />
  if (risk.kind === 'budget')
    return <Line icon={<AlertTriangle size={16} className="text-warning" />} text={t('dashboard.riskBudget', risk)} />
  if (risk.kind === 'partly')
    return (
      <Line
        icon={<ShieldAlert size={16} className="text-critical" />}
        text={t('dashboard.riskVerdict', { project: risk.project, verdict: t(`verdict.${risk.verdict}`) })}
      />
    )
  return <Line icon={<PauseCircle size={16} className="text-warning" />} text={t('dashboard.riskGates', risk)} />
}

function Line({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex items-start gap-2 text-sm text-text-2">
      <span className="mt-0.5 shrink-0">{icon}</span>
      {text}
    </div>
  )
}

function DeliveryView({ board }: { board: Dashboard }) {
  const { t } = useTranslation()
  const tasks = useTasks()
  const activity = useActivityStream()
  const d = board.delivery
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('dashboard.runningExecutions')} value={d.running} />
        <StatTile label={t('dashboard.gatesWaiting')} value={d.gatesWaiting} />
        <StatTile label={t('dashboard.escalations')} value={d.escalations} />
        <StatTile
          label={t('dashboard.tokensToday')}
          value={formatCompact(d.tokensToday)}
          hint={d.costTodayUsd != null ? formatCost(amount(d.costTodayUsd)) : undefined}
        />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('dashboard.liveActivity')} />
          <CardBody className="space-y-3">
            {activity.events.length === 0 && <p className="text-sm text-muted">{t('dashboard.noActivity')}</p>}
            {activity.events.slice(0, 12).map((e) => (
              <div key={e.id} className="flex gap-3 text-sm">
                <span className="w-28 shrink-0 text-xs text-muted tabular">{formatDateTime(e.occurredAt)}</span>
                <div className="min-w-0">
                  <div className="text-text">
                    <span className="font-medium">{e.agentKey ?? t('activity.panel.platform')}</span> ·{' '}
                    <span className="text-text-2">{t(`runEvent.${e.kind}`, { defaultValue: e.kind })}</span>
                  </div>
                  <div className="truncate text-xs text-muted">{e.message}</div>
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader
            title={t('dashboard.pendingApprovals')}
            action={
              <Link to="/tasks" className="text-sm font-medium text-brand hover:underline">
                {t('common.viewAll')}
              </Link>
            }
          />
          <CardBody className="space-y-2">
            {(tasks.data ?? []).length === 0 && <p className="text-sm text-muted">{t('dashboard.noTasks')}</p>}
            {(tasks.data ?? []).slice(0, 8).map((task) => (
              <Link
                key={`${task.kind}-${task.runId}-${task.gate ?? task.questionId}`}
                to="/tasks"
                className="flex items-center gap-3 rounded-md p-2 text-sm hover:bg-surface-2"
              >
                <Badge tone={task.impact === 'high' ? 'critical' : 'neutral'}>
                  {t(`dashboard.taskKinds.${task.kind}`)}
                </Badge>
                <span className="flex-1 truncate text-text">
                  {task.title} <span className="text-xs text-muted">· {task.projectName}</span>
                </span>
                <ArrowRight size={14} className="text-muted" aria-hidden />
              </Link>
            ))}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function AdminView({ board, tenants }: { board: Dashboard; tenants: number }) {
  const { t } = useTranslation()
  const admin = board.admin
  if (!admin) {
    return <EmptyState title={t('dashboard.adminOnly')} description={t('dashboard.adminOnlyHint')} />
  }
  const healthy = admin.connections.filter((c) => c.status === 'ok').length
  const month = board.monthlySpend.at(-1)
  const alerts = adminAlerts(admin)
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('dashboard.tenants')} value={tenants} />
        <StatTile
          label={t('dashboard.activeUsers')}
          value={formatNumber(admin.activeUsers)}
          hint={t('dashboard.pendingInvitations', { count: admin.pendingInvitations })}
        />
        <StatTile label={t('dashboard.monthSpend')} value={board.costVisible ? formatCost(amount(month?.usd)) : '—'} />
        <StatTile label={t('dashboard.connectionsHealthy')} value={`${healthy} / ${admin.connections.length}`} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('dashboard.spendByProject')} />
          <CardBody>
            {board.costVisible ? (
              <BarList
                data={board.projects
                  .filter((p) => amount(p.spentUsd) > 0)
                  .map((p) => ({ label: p.name, value: amount(p.spentUsd) }))}
                format={(v) => formatCost(v)}
              />
            ) : (
              <p className="text-sm text-muted">{t('dashboard.needsCostView')}</p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('dashboard.alerts')} />
          <CardBody className="space-y-3">
            {alerts.length === 0 && <p className="text-sm text-muted">{t('dashboard.noAlerts')}</p>}
            {alerts.map((a, i) =>
              a.kind === 'connection' ? (
                <Line
                  key={i}
                  icon={<PlugZap size={16} className="text-critical" />}
                  text={t('dashboard.alertConnection', { name: a.name })}
                />
              ) : (
                <Line
                  key={i}
                  icon={<AlertTriangle size={16} className="text-warning" />}
                  text={t('dashboard.alertBudget', {
                    project: a.project ?? t('dashboard.tenantBudget'),
                    level: a.level,
                  })}
                />
              ),
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
