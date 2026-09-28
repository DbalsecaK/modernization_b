import { useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ArrowRight, PauseCircle, PlugZap, ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatCompact, formatMonth, formatUsd } from '@/lib/format'
import { connections, monthlyCost, projects, runEvents, tasks, tenants, users } from '@/mocks/data'
import { Badge, Card, CardBody, CardHeader, PageHeader, Progress, StatTile } from '@/components/ui/primitives'
import { PhaseStatusIcon, VerdictBadge } from '@/components/ui/status'
import { BarList, LineChart } from '@/components/charts/charts'

type Perspective = 'executive' | 'delivery' | 'admin'

export function DashboardPage() {
  const { t } = useTranslation()
  const [perspective, setPerspective] = useState<Perspective>('executive')

  return (
    <>
      <PageHeader
        title={t('dashboard.title')}
        description={t('dashboard.description')}
        actions={
          <div className="flex rounded-md border border-border bg-surface p-0.5 text-sm" role="group" aria-label={t('dashboard.perspective')}>
            {(['executive', 'delivery', 'admin'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPerspective(p)}
                aria-pressed={perspective === p}
                className={cn('rounded px-3 py-1.5', perspective === p ? 'bg-brand text-brand-contrast' : 'text-text-2 hover:text-text')}
              >
                {t(`dashboard.perspectives.${p}`)}
              </button>
            ))}
          </div>
        }
      />
      {perspective === 'executive' && <ExecutiveView />}
      {perspective === 'delivery' && <DeliveryView />}
      {perspective === 'admin' && <AdminView />}
    </>
  )
}

function ExecutiveView() {
  const { t } = useTranslation()
  const active = projects.filter((p) => p.progress < 100)
  const totalRules = projects.reduce((s, p) => s + p.rules.total, 0)
  const verified = projects.reduce((s, p) => s + p.rules.verified, 0)
  const spent = projects.reduce((s, p) => s + p.costUsd, 0)
  const budget = projects.reduce((s, p) => s + p.budgetUsd, 0)
  const proven = projects.filter((p) => p.verdict === 'PROVEN').length

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('dashboard.activeProjects')} value={active.length} hint={t('dashboard.ofTotal', { total: projects.length })} />
        <StatTile label={t('dashboard.rulesVerified')} value={`${verified} / ${totalRules}`} hint={t('dashboard.rulesVerifiedHint')} />
        <StatTile label={t('dashboard.provenModules')} value={proven} hint={t('dashboard.provenHint')} />
        <StatTile label={t('dashboard.spendVsBudget')} value={formatUsd(spent)} hint={t('dashboard.budgetOf', { budget: formatUsd(budget) })} />
      </div>
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title={t('dashboard.projectProgress')} action={<Link to="/projects" className="text-sm font-medium text-info hover:underline">{t('common.viewAll')}</Link>} />
          <CardBody className="divide-y divide-border p-0">
            {projects.map((p) => {
              const current = p.phases.find((ph) => ph.status !== 'done') ?? p.phases[p.phases.length - 1]
              return (
                <Link key={p.id} to="/projects/$projectId" params={{ projectId: p.id }} className="flex items-center gap-4 px-5 py-3 hover:bg-surface-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text">{p.name}</div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted">
                      <PhaseStatusIcon status={current.status} size={12} />
                      {t(`phases.${current.key}`)}
                    </div>
                  </div>
                  <div className="hidden w-40 shrink-0 sm:block">
                    <Progress value={p.progress} />
                    <div className="mt-1 text-right text-xs text-muted tabular">{p.progress}%</div>
                  </div>
                  <div className="flex w-32 shrink-0 justify-end">
                    <VerdictBadge verdict={p.verdict} />
                  </div>
                </Link>
              )
            })}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('dashboard.risks')} />
          <CardBody className="space-y-3">
            <Risk icon={<AlertTriangle size={16} className="text-warning" />} text={t('dashboard.riskBudget', { project: 'Card Management', pct: 80 })} />
            <Risk icon={<PauseCircle size={16} className="text-warning" />} text={t('dashboard.riskGate', { count: 148 })} />
            <Risk icon={<ShieldAlert size={16} className="text-critical" />} text={t('dashboard.riskPartly', { project: 'Interest Accrual SP' })} />
          </CardBody>
        </Card>
      </div>
      <Card>
        <CardHeader title={t('dashboard.monthlySpend')} subtitle={t('dashboard.monthlySpendHint')} />
        <CardBody>
          <LineChart data={monthlyCost.map((m) => ({ x: formatMonth(m.month), y: m.usd }))} format={(v) => formatUsd(v)} label={t('dashboard.monthlySpend')} />
        </CardBody>
      </Card>
    </div>
  )
}

function Risk({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex items-start gap-2 text-sm text-text-2">
      <span className="mt-0.5 shrink-0">{icon}</span>
      {text}
    </div>
  )
}

function DeliveryView() {
  const { t } = useTranslation()
  const running = projects.filter((p) => p.phases.some((ph) => ph.status === 'running'))
  const waiting = projects.filter((p) => p.phases.some((ph) => ph.status === 'waiting'))
  const escalations = runEvents.filter((e) => e.kind === 'escalated')
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('dashboard.runningExecutions')} value={running.length} />
        <StatTile label={t('dashboard.gatesWaiting')} value={waiting.length} />
        <StatTile label={t('dashboard.escalations')} value={escalations.length} />
        <StatTile label={t('dashboard.tokensToday')} value={formatCompact(8_400_000)} hint={formatUsd(214)} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('dashboard.liveActivity')} />
          <CardBody className="space-y-3">
            {runEvents.slice().reverse().map((e) => (
              <div key={e.id} className="flex gap-3 text-sm">
                <span className="w-16 shrink-0 text-xs text-muted tabular">{e.time}</span>
                <div className="min-w-0">
                  <div className="text-text">
                    <span className="font-medium">{e.agent}</span> · <span className="text-text-2">{t(`runEvent.${e.kind}`)}</span>
                  </div>
                  <div className="text-xs text-muted">{e.detail}</div>
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('dashboard.pendingApprovals')} action={<Link to="/tasks" className="text-sm font-medium text-info hover:underline">{t('common.viewAll')}</Link>} />
          <CardBody className="space-y-2">
            {tasks.map((task) => (
              <Link key={task.id} to="/tasks" className="flex items-center gap-3 rounded-md p-2 text-sm hover:bg-surface-2">
                <Badge tone={task.priority === 'high' ? 'critical' : 'neutral'}>{t(`tasks.kinds.${task.kind}`)}</Badge>
                <span className="flex-1 truncate text-text">{task.title}</span>
                <ArrowRight size={14} className="text-muted" />
              </Link>
            ))}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function AdminView() {
  const { t } = useTranslation()
  const activeUsers = users.filter((u) => u.status === 'active').length
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('dashboard.tenants')} value={tenants.length} />
        <StatTile label={t('dashboard.activeUsers')} value={activeUsers} hint={t('dashboard.withoutMfa', { count: users.filter((u) => !u.mfa).length })} />
        <StatTile label={t('dashboard.monthSpend')} value={formatUsd(tenants.reduce((s, x) => s + x.monthCostUsd, 0))} />
        <StatTile label={t('dashboard.connectionsHealthy')} value={`${connections.filter((c) => c.status === 'connected').length} / ${connections.length}`} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('dashboard.spendByTenant')} />
          <CardBody>
            <BarList data={tenants.map((x) => ({ label: x.name, value: x.monthCostUsd }))} format={(v) => formatUsd(v)} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('dashboard.alerts')} />
          <CardBody className="space-y-3">
            <Risk icon={<PlugZap size={16} className="text-critical" />} text={t('dashboard.alertConnection', { name: 'NexTI — Anthropic API' })} />
            <Risk icon={<AlertTriangle size={16} className="text-warning" />} text={t('dashboard.alertMfa', { name: 'Jorge Mena' })} />
            <Risk icon={<AlertTriangle size={16} className="text-warning" />} text={t('dashboard.alertWorker', { name: 'w-sandbox-win-1' })} />
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
