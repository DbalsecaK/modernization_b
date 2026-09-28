import { useTranslation } from 'react-i18next'
import { AlertTriangle, CheckCircle2, CircleDashed, GitBranch, RefreshCw, ShieldCheck, Split, XCircle } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatCompact, formatDateTime, formatUsd } from '@/lib/format'
import { agents, auditLog, costByAgent, costByPhase, projects, runEvents } from '@/mocks/data'
import type { Project, RunEvent } from '@/mocks/types'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Progress, StatTile, Table, Td, Th } from '@/components/ui/primitives'
import { VerdictBadge } from '@/components/ui/status'
import { BarList } from '@/components/charts/charts'
import { agentName } from '@/features/catalog/AgentCard'
import { Notice } from '../NewProjectWizard'

type CheckState = 'pass' | 'gap' | 'fail' | 'na'

const checksByProject: Record<string, { id: string; state: CheckState; detail: string }[]> = {
  p2: [
    { id: 'tests', state: 'pass', detail: '412 tests executed from clean, 0 failed (JUnit XML parsed).' },
    { id: 'rules', state: 'gap', detail: '4 of 31 P0 rules are named only by tests that did not run: RULE-012, RULE-019, RULE-027, RULE-030.' },
    { id: 'same', state: 'pass', detail: '86 development cases: 86 same after masks (run timestamp).' },
    { id: 'fresh', state: 'pass', detail: '14 fresh inputs, no differences.' },
    { id: 'canary', state: 'pass', detail: 'Rounding mode HALF_UP → HALF_EVEN: 9 tests failed.' },
    { id: 'source', state: 'pass', detail: 'No file under legacy/ is newer than the preflight.' },
  ],
  p5: [
    { id: 'tests', state: 'pass', detail: '188 tests executed, 0 failed.' },
    { id: 'rules', state: 'pass', detail: 'All 18 rules backed by a passing acceptance test.' },
    { id: 'same', state: 'na', detail: 'New feature: acceptance tests are the oracle.' },
    { id: 'fresh', state: 'na', detail: 'New feature: no legacy to compare.' },
    { id: 'canary', state: 'pass', detail: 'Interest rate threshold +1: 3 tests failed.' },
    { id: 'source', state: 'na', detail: 'No legacy source.' },
  ],
}

const stateIcon = {
  pass: <CheckCircle2 size={16} className="text-good" />,
  gap: <AlertTriangle size={16} className="text-warning" />,
  fail: <XCircle size={16} className="text-critical" />,
  na: <CircleDashed size={16} className="text-muted" />,
}

export function ValidationTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const checks = checksByProject[project.id]
  if (!checks) {
    return <Notice tone="info">{t('validation.notYet')}</Notice>
  }
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={t('validation.verdict')}
          subtitle={t('validation.computedByCode')}
          action={<VerdictBadge verdict={project.verdict} />}
        />
        <CardBody className="space-y-3">
          {checks.map((c) => (
            <div key={c.id} className="flex items-start gap-3 rounded-md border border-border p-3">
              <span className="mt-0.5" aria-label={t(`validation.state.${c.state}`)}>
                {stateIcon[c.state]}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-text">{t(`validation.checks.${c.id}`)}</div>
                <div className="text-sm text-text-2">{c.detail}</div>
              </div>
              <Badge tone={c.state === 'pass' ? 'good' : c.state === 'gap' ? 'warning' : c.state === 'fail' ? 'critical' : 'neutral'}>
                {t(`validation.state.${c.state}`)}
              </Badge>
            </div>
          ))}
        </CardBody>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('validation.doesNotProve')} />
          <CardBody>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-text-2">
              {(['samples', 'masks', 'unextracted', 'nonFunctional', 'signoff'] as const).map((k) => (
                <li key={k}>{t(`validation.limits.${k}`)}</li>
              ))}
            </ul>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('validation.signoff')} subtitle={t('validation.signoffHint')} />
          <CardBody className="space-y-4">
            <Field label={t('validation.signerName')}>
              <Input placeholder="Luis Andrade" />
            </Field>
            <Field label={t('validation.comment')}>
              <Input placeholder={t('validation.commentPlaceholder')} />
            </Field>
            <Button variant="primary" disabled={project.verdict !== 'PROVEN'}>
              <ShieldCheck size={16} /> {t('validation.sign')}
            </Button>
            {project.verdict !== 'PROVEN' && <p className="text-xs text-muted">{t('validation.signDisabled')}</p>}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

const eventStyle: Record<RunEvent['kind'], { Icon: typeof CheckCircle2; className: string }> = {
  started: { Icon: RefreshCw, className: 'text-info' },
  completed: { Icon: CheckCircle2, className: 'text-good' },
  verificationFailed: { Icon: XCircle, className: 'text-critical' },
  selfCorrected: { Icon: RefreshCw, className: 'text-info' },
  escalated: { Icon: AlertTriangle, className: 'text-warning' },
  gateWaiting: { Icon: CircleDashed, className: 'text-warning' },
  fanOut: { Icon: Split, className: 'text-info' },
}

const shards = ['ACCT', 'CARD', 'AUTH', 'BILL', 'CUST', 'STMT', 'TRAN', 'USER', 'RPT', 'BATCH', 'MENU', 'UTIL']

export function RunsTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('runs.currentRun')} value="run-0007" hint={t('runs.startedAt', { time: '09:14' })} />
        <StatTile label={t('runs.subagents')} value="12" hint={t('runs.subagentsHint')} />
        <StatTile label={t('runs.selfCorrections')} value="3" hint={t('runs.selfCorrectionsHint', { max: 3 })} />
        <StatTile label={t('runs.escalations')} value="1" />
      </div>
      <Card>
        <CardHeader title={t('runs.fanOut')} subtitle={t('runs.fanOutHint')} action={<Badge tone="info">{t('runs.live')}</Badge>} />
        <CardBody className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {shards.map((s, i) => {
            const value = project.id === 'p1' ? 100 : Math.min(100, 40 + i * 7)
            return (
              <div key={s} className="rounded-md border border-border p-2.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-text">{s}</span>
                  <span className="text-muted tabular">{value}%</span>
                </div>
                <div className="mt-2">
                  <Progress value={value} />
                </div>
              </div>
            )
          })}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('runs.timeline')} />
        <CardBody>
          <ol className="relative space-y-5 border-l border-border pl-6">
            {runEvents.map((e) => {
              const { Icon, className } = eventStyle[e.kind]
              return (
                <li key={e.id} className="relative">
                  <span className="absolute top-0.5 -left-[33px] rounded-full bg-surface p-0.5">
                    <Icon size={16} className={className} />
                  </span>
                  <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                    <span className="text-xs text-muted tabular">{e.time}</span>
                    <span className="font-medium text-text">{e.agent}</span>
                    <span className="text-text-2">{t(`runEvent.${e.kind}`)}</span>
                    <span className="text-xs text-muted">· {t(`phases.${e.phase}`)}</span>
                    {e.tokens && <span className="text-xs text-muted">· {t('runs.tokens', { value: formatCompact(e.tokens) })}</span>}
                  </div>
                  <p className="mt-0.5 text-sm text-text-2">{e.detail}</p>
                </li>
              )
            })}
          </ol>
        </CardBody>
      </Card>
    </div>
  )
}

export function CostsTab({ project }: { project: Project }) {
  const { t, i18n } = useTranslation()
  const pct = Math.round((project.costUsd / project.budgetUsd) * 100)
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('costs.spent')} value={formatUsd(project.costUsd)} hint={<Progress value={pct} tone={pct >= 80 ? 'warning' : 'brand'} />} />
        <StatTile label={t('costs.budget')} value={formatUsd(project.budgetUsd)} hint={t('costs.used', { pct })} />
        <StatTile label={t('costs.tokens')} value={formatCompact(project.tokens)} />
        <StatTile label={t('costs.forecast')} value={formatUsd(project.costUsd / Math.max(project.progress, 1) * 100)} hint={t('costs.forecastHint')} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('costs.byPhase')} />
          <CardBody>
            <BarList data={costByPhase.map((c) => ({ label: t(`phases.${c.key}`), value: c.usd }))} format={(v) => formatUsd(v)} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('costs.byAgent')} />
          <CardBody>
            <BarList
              data={costByAgent.map((c) => ({ label: agentName(agents.find((a) => a.id === c.key)!, i18n.language), value: c.usd }))}
              format={(v) => formatUsd(v)}
            />
          </CardBody>
        </Card>
      </div>
      <Notice tone="info">{t('costs.selfCorrectionShare', { usd: formatUsd(212), pct: 12 })}</Notice>
    </div>
  )
}

export function ActivityTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const entries = auditLog.filter((a) => a.target.startsWith(project.id))
  return (
    <Card>
      <CardHeader title={t('activity.title')} subtitle={t('activity.subtitle')} />
      {entries.length === 0 ? (
        <CardBody>
          <p className="text-sm text-muted">{t('activity.empty')}</p>
        </CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('activity.time')}</Th>
              <Th>{t('activity.actor')}</Th>
              <Th>{t('activity.action')}</Th>
              <Th>{t('activity.target')}</Th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <Td>{formatDateTime(e.time)}</Td>
                <Td className="text-text">{e.actor}</Td>
                <Td className="font-mono text-xs">{e.action}</Td>
                <Td>{e.target}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

export function SettingsTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const other = projects.filter((p) => p.id !== project.id).length
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title={t('projectSettings.general')} />
        <CardBody className="space-y-4">
          <Field label={t('wizard.projectName')}>
            <Input defaultValue={project.name} />
          </Field>
          <Field label={t('wizard.budget')}>
            <Input type="number" defaultValue={project.budgetUsd} />
          </Field>
          <Field label={t('wizard.maxIterations')}>
            <Input type="number" defaultValue={3} />
          </Field>
          <Button variant="primary">{t('common.save')}</Button>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('projectSettings.teamAndAgents')} />
        <CardBody className="space-y-3 text-sm">
          <SettingRow label={t('projectSettings.agents')} value={t('wizard.agentsSelected', { count: 15 })} />
          <SettingRow label={t('projectSettings.skills')} value={t('wizard.skillsSelected', { count: 14 })} />
          <SettingRow label={t('projectSettings.models')} value={t('projectSettings.inherited')} />
          <SettingRow label={t('projectSettings.pipeline')} value={t('templates.bankStandard.name')} />
          <SettingRow label={t('projectSettings.versions')} value={t('projectSettings.pinned')} />
          <p className="pt-2 text-xs text-muted">{t('projectSettings.changeNote', { count: other })}</p>
        </CardBody>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title={t('projectSettings.integrations')} />
        <CardBody className="grid gap-3 sm:grid-cols-3">
          {[
            ['GitHub', 'andesbank/card-management', true],
            ['Jira', 'CARDS', true],
            ['Figma', '—', false],
          ].map(([name, detail, on]) => (
            <div key={name as string} className={cn('flex items-center gap-3 rounded-md border border-border p-3')}>
              <GitBranch size={16} className="text-muted" />
              <div className="flex-1 text-sm">
                <div className="text-text">{name}</div>
                <div className="text-xs text-muted">{detail}</div>
              </div>
              <Badge tone={on ? 'good' : 'neutral'}>{on ? t('common.connected') : t('common.notConnected')}</Badge>
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border pb-2 last:border-0">
      <span className="text-muted">{label}</span>
      <span className="text-right text-text">{value}</span>
    </div>
  )
}
