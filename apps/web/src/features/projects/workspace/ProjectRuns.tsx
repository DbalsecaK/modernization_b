import { useState, type ReactElement } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Loader2,
  PauseCircle,
  Play,
  RotateCw,
  Square,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime, formatNumber, formatUsd } from '@/lib/format'
import { ApiError } from '@/api/client'
import type { ProjectDetail } from '@/api/projects'
import {
  ACTIVE_STATUSES,
  useActivityStream,
  useCancelRun,
  useRetryRun,
  useDecideGate,
  useRun,
  useRuns,
  useStartRun,
  type Gate,
  type GateRow,
  type RunDetail,
} from '@/api/runs'
import { useMe } from '@/api/session'
import { useIvv } from '@/api/ivv'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Select,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'
import { Textarea, toast } from '@/components/ui/overlay'
import { QuestionList } from '@/features/decisions/QuestionCard'

const GATE_PERMISSION = {
  C1: 'gate.c1.approve',
  C2: 'gate.c2.approve',
  C3: 'gate.c3.approve',
  C4: 'signoff.sign',
} as const

const phaseIcon: Record<string, ReactElement> = {
  pending: <Circle size={14} className="text-muted" />,
  running: <Loader2 size={14} className="animate-spin text-info" />,
  waiting: <PauseCircle size={14} className="text-warning" />,
  unavailable: <PauseCircle size={14} className="text-muted" />,
  succeeded: <CheckCircle2 size={14} className="text-good" />,
  failed: <XCircle size={14} className="text-critical" />,
  skipped: <Circle size={14} className="text-muted" />,
}

const statusTone = {
  queued: 'neutral',
  running: 'info',
  waiting: 'warning',
  succeeded: 'good',
  failed: 'critical',
  cancelled: 'neutral',
} as const

function errorText(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback
}

// Runs of the project (spec 10, 18.4): launch the pipeline, follow its phases live, decide its gates, answer its
// questions. Everything comes from the API; the worker does the work.
export function ProjectRuns({ project }: { project: ProjectDetail }) {
  const { t } = useTranslation()
  const runs = useRuns(project.id)
  const [selected, setSelected] = useState<string | null>(null)
  const start = useStartRun(project.id)
  const current = selected ?? runs.data?.[0]?.id ?? null
  const detail = useRun(project.id, current)
  const active = runs.data?.some((r) => ACTIVE_STATUSES.includes(r.status)) ?? false
  const canRun = project.permissions.includes('pipeline.run')

  const launch = (kind: 'pipeline' | 'demo') =>
    start.mutate(
      { kind },
      {
        onSuccess: (run) => {
          setSelected(run.id)
          toast(t('runsPage.started'))
        },
        onError: (e) => toast(errorText(e, t('common.error'))),
      },
    )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          disabled={!canRun || active || !project.config || start.isPending}
          onClick={() => launch('pipeline')}
        >
          <Play size={16} /> {t('runsPage.runPipeline')}
        </Button>
        {import.meta.env.DEV && (
          <Button disabled={!canRun || active || !project.config || start.isPending} onClick={() => launch('demo')}>
            <Play size={16} /> {t('runsPage.runDemo')}
          </Button>
        )}
        {!project.config && <span className="text-sm text-muted">{t('runsPage.configureFirst')}</span>}
        {active && <span className="text-sm text-muted">{t('runsPage.oneAtATime')}</span>}
      </div>

      {runs.data && runs.data.length === 0 ? (
        <EmptyState title={t('project.later.runs')} description={t('runsPage.emptyHint')} />
      ) : (
        <div className="grid gap-6 xl:grid-cols-[260px_1fr]">
          <Card>
            <CardHeader title={t('runsPage.history')} />
            <ul className="divide-y divide-border">
              {(runs.data ?? []).map((run) => (
                <li key={run.id}>
                  <button
                    onClick={() => setSelected(run.id)}
                    aria-current={run.id === current}
                    className={cn(
                      'flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-surface-2',
                      run.id === current && 'bg-surface-2',
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <Badge tone={statusTone[run.status]}>{t(`runsPage.status.${run.status}`)}</Badge>
                      {run.kind === 'demo' && <Badge>{t('runsPage.demo')}</Badge>}
                    </span>
                    <span className="text-xs text-muted">{formatDateTime(run.createdAt)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {detail.data && <RunView project={project} run={detail.data} />}
        </div>
      )}
    </div>
  )
}

function RunView({ project, run }: { project: ProjectDetail; run: RunDetail }) {
  const { t } = useTranslation()
  const me = useMe()
  const cancel = useCancelRun(project.id)
  const retry = useRetryRun(project.id)
  // A failed run may start again from the failed phase or an earlier one; a finished run, from any phase (ADR-0035).
  const failedAt = run.status === 'failed' ? run.phases.findIndex((p) => p.phase === run.currentPhase) : -1
  const retryable = failedAt >= 0 ? run.phases.slice(0, failedAt + 1) : run.phases
  const [retryFrom, setRetryFrom] = useState<string>('')
  const live = ACTIVE_STATUSES.includes(run.status)
  const { events } = useActivityStream({ projectId: project.id, runId: run.id }, true)
  const canAnswer = project.permissions.includes('question.answer')
  const pendingGates = run.gates.filter((g) => g.status === 'pending' && g.required)
  const tokens = run.invocations.reduce((s, i) => s + i.inputTokens + i.outputTokens, 0)
  const cost = run.invocations.reduce((s, i) => s + Number(i.costUsd ?? 0), 0)

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={t('runs.currentRun')}
          subtitle={t('runsPage.summary', {
            status: t(`runsPage.status.${run.status}`),
            by: run.startedByName ?? '—',
            date: formatDateTime(run.createdAt),
          })}
          action={
            live && project.permissions.includes('pipeline.run') ? (
              <Button
                size="sm"
                disabled={cancel.isPending}
                onClick={() => cancel.mutate(run.id, { onError: (e) => toast(errorText(e, t('common.error'))) })}
              >
                <Square size={14} /> {t('runsPage.cancel')}
              </Button>
            ) : (run.status === 'failed' || run.status === 'succeeded') &&
              project.permissions.includes('pipeline.run') ? (
              <div className="flex items-center gap-2">
                <Select
                  aria-label={t('runsPage.retryFrom')}
                  value={retryFrom || run.currentPhase || ''}
                  onChange={(e) => setRetryFrom(e.target.value)}
                >
                  {retryable.map((p) => (
                    <option key={p.phase} value={p.phase}>
                      {t(`phases.${p.phase}`, { defaultValue: p.phase })}
                    </option>
                  ))}
                </Select>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={retry.isPending}
                  onClick={() =>
                    retry.mutate(
                      { runId: run.id, phase: retryFrom || null },
                      {
                        onSuccess: () => toast(t('runsPage.retried')),
                        onError: (e) => toast(errorText(e, t('common.error'))),
                      },
                    )
                  }
                >
                  <RotateCw size={14} /> {t('runsPage.retry')}
                </Button>
              </div>
            ) : undefined
          }
        />
        <CardBody className="space-y-4">
          {run.status === 'waiting' && run.waitingReason && (
            <div className="flex items-start gap-2 rounded-md bg-warning/10 p-3 text-sm">
              <PauseCircle size={16} className="mt-0.5 shrink-0 text-warning" />
              <span>
                {t(`runsPage.waiting.${run.waitingReason}`, {
                  phase: t(`phases.${run.currentPhase}`, { defaultValue: run.currentPhase ?? '' }),
                })}
              </span>
            </div>
          )}
          {run.error && (
            <div className="flex items-start gap-2 rounded-md bg-critical/8 p-3 text-sm">
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-critical" />
              <span className="text-text">{run.error}</span>
            </div>
          )}
          <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label={t('overview.pipeline')}>
            {run.phases.map((phase) => (
              <li key={phase.phase} className="flex items-start gap-2 rounded-md border border-border px-3 py-2">
                <span className="mt-0.5">{phaseIcon[phase.status] ?? phaseIcon.pending}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-text">
                    {t(`phases.${phase.phase}`, { defaultValue: phase.phase })}
                  </span>
                  <span className="block text-xs text-muted">
                    {t(`runsPage.phaseStatus.${phase.status}`)}
                    {phase.iterations > 1 && ` · ${t('runsPage.attempts', { count: phase.iterations })}`}
                  </span>
                  {phase.detail && phase.status !== 'pending' && (
                    <span className="block truncate text-xs text-text-2" title={phase.detail}>
                      {phase.detail}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-4 text-xs text-muted tabular">
            <span>{t('runs.tokens', { value: formatNumber(tokens) })}</span>
            {run.costVisible && <span>{formatUsd(cost, 2)}</span>}
            <span>{t('runsPage.invocations', { count: run.invocations.length })}</span>
          </div>
        </CardBody>
      </Card>

      {pendingGates.map((gate) => (
        <GateCard
          key={gate.gate}
          project={project}
          runId={run.id}
          gate={gate}
          launchedByMe={run.startedBy === me?.user.id}
        />
      ))}

      {run.questions.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-text">{t('runsPage.questions')}</h2>
          <QuestionList questions={run.questions} canAnswer={() => canAnswer} />
        </section>
      )}

      <Card>
        <CardHeader title={t('runsPage.invocationsTitle')} />
        <Table>
          <thead>
            <tr>
              <Th>{t('runsPage.columns.phase')}</Th>
              <Th>{t('runsPage.columns.agent')}</Th>
              <Th>{t('runsPage.columns.attempt')}</Th>
              <Th>{t('runsPage.columns.status')}</Th>
              <Th className="text-right">{t('runsPage.columns.tokens')}</Th>
              {run.costVisible && <Th className="text-right">{t('runsPage.columns.cost')}</Th>}
            </tr>
          </thead>
          <tbody>
            {run.invocations.map((i) => (
              <tr key={i.id} title={i.error ? JSON.stringify(i.error) : (i.summary ?? undefined)}>
                <Td>{t(`phases.${i.phase}`, { defaultValue: i.phase })}</Td>
                <Td>
                  {i.agentKey}
                  {i.shard && <span className="ml-1 font-mono text-xs text-muted">[{i.shard}]</span>}
                </Td>
                <Td className="tabular">{i.iteration}</Td>
                <Td>
                  <Badge tone={i.status === 'succeeded' ? 'good' : i.status === 'running' ? 'info' : 'critical'}>
                    {t(`runsPage.invocationStatus.${i.status}`)}
                  </Badge>
                </Td>
                <Td className="text-right tabular">{formatNumber(i.inputTokens + i.outputTokens)}</Td>
                {run.costVisible && <Td className="text-right tabular">{formatUsd(Number(i.costUsd ?? 0), 4)}</Td>}
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card>
        <CardHeader title={t('runs.timeline')} subtitle={live ? t('runs.live') : undefined} />
        <ul
          className="max-h-96 divide-y divide-border overflow-y-auto"
          aria-live="polite"
          tabIndex={0}
          aria-label={t('runs.timeline')}
        >
          {events.map((e) => (
            <li key={e.id} className="flex items-start gap-3 px-5 py-2 text-sm">
              <span className="w-20 shrink-0 text-xs text-muted tabular">
                {new Date(e.occurredAt).toLocaleTimeString()}
              </span>
              <Badge
                tone={
                  e.status === 'failed'
                    ? 'critical'
                    : e.status === 'waiting'
                      ? 'warning'
                      : e.status === 'succeeded'
                        ? 'good'
                        : 'info'
                }
              >
                {t(`runsPage.eventKind.${e.kind}`, { defaultValue: e.kind })}
              </Badge>
              <span className="min-w-0 flex-1 text-text-2">
                {e.agentKey && <span className="mr-1 font-medium text-text">{e.agentKey}</span>}
                {e.message}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

function GateCard({
  project,
  runId,
  gate,
  launchedByMe,
}: {
  project: ProjectDetail
  runId: string
  gate: GateRow
  launchedByMe: boolean
}) {
  const { t } = useTranslation()
  const decide = useDecideGate(project.id)
  const [comment, setComment] = useState('')
  const key = gate.gate as Gate
  const allowed = project.permissions.includes(GATE_PERMISSION[key]) && !launchedByMe
  // Flow 4's C2 approves the interface mapping (ADR-0025): the approver sees whether it is complete first.
  const ivvMapping = project.flow === 'independentValidation' && key === 'C2'
  const send = (approve: boolean) =>
    decide.mutate(
      { runId, gate: key, approve, comment },
      {
        onSuccess: () => toast(t(approve ? 'runsPage.gate.approved' : 'runsPage.gate.rejected', { gate: key })),
        onError: (e) => toast(errorText(e, t('common.error'))),
      },
    )
  return (
    <Card>
      <CardHeader
        title={t('runsPage.gate.title', { gate: key })}
        subtitle={ivvMapping ? t('runsPage.gate.ivvHint') : t(`runsPage.gate.hint.${key}`)}
      />
      <CardBody className="space-y-3">
        {ivvMapping && <IvvMappingStatus projectId={project.id} />}
        {launchedByMe && <p className="text-sm text-muted">{t('runsPage.gate.segregation')}</p>}
        {!allowed && !launchedByMe && <p className="text-sm text-muted">{t('runsPage.gate.noPermission')}</p>}
        <Textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          disabled={!allowed}
          placeholder={t('runsPage.gate.comment')}
          aria-label={t('runsPage.gate.comment')}
        />
        <div className="flex gap-2">
          <Button variant="primary" disabled={!allowed || decide.isPending} onClick={() => send(true)}>
            {t('runsPage.gate.approve')}
          </Button>
          <Button disabled={!allowed || decide.isPending || !comment.trim()} onClick={() => send(false)}>
            {t('runsPage.gate.reject')}
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

/** Gate C2 of Flow 4: the mapping's problems the server found, with a link to correct them in the IV&V tab. */
function IvvMappingStatus({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const ivv = useIvv(projectId)
  const open = () =>
    void navigate({ to: '.', search: ((prev: Record<string, unknown>) => ({ ...prev, tab: 'ivv' })) as never })
  const problems = ivv.data?.problems.length ?? 0
  const status = ivv.isLoading
    ? t('ivv.loading')
    : ivv.isError || !ivv.data
      ? t('runsPage.gate.ivvUnknown')
      : ivv.data.mapping === null
        ? t('runsPage.gate.ivvNoMapping')
        : problems > 0
          ? t('runsPage.gate.ivvProblems', { count: problems })
          : t('runsPage.gate.ivvReady')
  const tone = ivv.data && ivv.data.mapping !== null && problems === 0 ? 'bg-good/10' : 'bg-warning/12'
  return (
    <div className={cn('flex flex-wrap items-center gap-3 rounded-md p-3 text-sm', tone)} role="status">
      <span className="min-w-0 flex-1 text-text-2">{status}</span>
      <Button size="sm" onClick={open}>
        {t('runsPage.gate.ivvOpen')}
      </Button>
    </div>
  )
}
