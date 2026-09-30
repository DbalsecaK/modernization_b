import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Ban,
  GripVertical,
  Plus,
  RotateCcw,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { planDiff } from '@/lib/migrationPlan'
import { ApiError } from '@/api/client'
import { useResetPlan, useSavePlan, type PlanOut, type PlanProblem, type StoryOut } from '@/api/spec'
import { Badge, Button, Card, CardBody, CardHeader, Toggle } from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'
import { Notice } from '../../NewProjectWizard'
import { dependenciesOf, camelKey, moveInWaves, newProblems, planProblemsOf, sameWaves, storyStatusTone } from './model'
import { errorText, IconBtn } from './shared'

// Migration plan by waves (spec 7.7). The platform suggests it from the story dependencies; people reorder it and the
// server validates every change: before a hard dependency the change is rejected, before a soft one it is saved with
// a warning (a temporary ACL or stub is planned).
export function PlanView({
  projectId,
  plan,
  stories,
  canEdit,
}: {
  projectId: string
  plan: PlanOut
  stories: StoryOut[]
  canEdit: boolean
}) {
  const { t } = useTranslation()
  const save = useSavePlan(projectId)
  const reset = useResetPlan(projectId)
  const [dragging, setDragging] = useState<string | null>(null)
  const [showDiff, setShowDiff] = useState(true)
  const [rejected, setRejected] = useState<{ story: string; problems: PlanProblem[]; message: string } | null>(null)
  const byKey = new Map(stories.map((s) => [s.key, s]))
  const problems = [...plan.errors, ...plan.warnings]
  const diff = planDiff(plan.suggested, plan.waves)
  const waves = [...plan.waves, []]
  const busy = save.isPending || reset.isPending

  function move(key: string, toWave: number, index?: number) {
    if (!canEdit || busy) return
    const next = moveInWaves(plan.waves, key, toWave, index)
    if (sameWaves(next, plan.waves)) return
    save.mutate(
      { waves: next, changeNote: null },
      {
        onSuccess: (saved) => {
          setRejected(null)
          const added = newProblems(plan.warnings, saved.warnings).filter((p) => p.story === key || p.on === key)
          toast(
            added.length > 0
              ? t('storyPlan.movedWithWarning', { id: key })
              : t('storyPlan.saved', { version: saved.version }),
          )
        },
        onError: (e) => {
          // The rejection card explains it (toasts are for confirmations only).
          if (e instanceof ApiError && e.code === 'invalid_plan')
            setRejected({ story: key, problems: planProblemsOf(e.problems), message: e.message })
          else toast(errorText(e, t('common.error')))
        },
      },
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Notice tone="info">{t('storyPlan.hint')}</Notice>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Toggle checked={showDiff} onChange={setShowDiff} label={t('storyPlan.showDiff')} />
          {canEdit && (
            <Button
              size="sm"
              disabled={!plan.differsFromSuggested || busy}
              onClick={() =>
                reset.mutate(undefined, {
                  onSuccess: () => {
                    setRejected(null)
                    toast(t('storyPlan.resetDone'))
                  },
                  onError: (e) => toast(errorText(e, t('common.error'))),
                })
              }
            >
              <RotateCcw size={14} /> {t('storyPlan.reset')}
            </Button>
          )}
        </div>
      </div>
      <p className="text-xs text-muted">
        {t('storyPlan.version', {
          version: plan.version,
          by: plan.createdByName ?? t('stories.byPlatform'),
          date: formatDateTime(plan.createdAt),
        })}
        {plan.changeNote && ` · ${plan.changeNote}`}
      </p>
      {!canEdit && <Notice tone="warning">{t('storyPlan.readOnly')}</Notice>}

      {rejected && (
        <Card className="border-critical">
          <CardHeader
            title={
              <span className="flex items-center gap-1.5 text-critical-ink" role="alert">
                <Ban size={14} /> {t('storyPlan.rejected', { id: rejected.story })}
              </span>
            }
          />
          <CardBody className="space-y-1 text-sm">
            {rejected.problems.length === 0 ? (
              <p className="text-text-2">{rejected.message}</p>
            ) : (
              rejected.problems.map((p) => (
                <p key={`${p.code}${p.story}${p.on}`} className="text-text-2">
                  <ProblemText problem={p} />
                </p>
              ))
            )}
          </CardBody>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {waves.map((wave, w) => {
          const items = wave.map((k) => byKey.get(k)).filter(Boolean) as StoryOut[]
          const isNew = w === plan.waves.length
          if (isNew && !canEdit) return null
          return (
            <Card
              key={w}
              className={cn('flex flex-col', dragging && 'border-dashed', isNew && 'border-dashed bg-surface-2')}
            >
              <div
                className="flex-1"
                role="region"
                aria-label={isNew ? t('storyPlan.newWave') : t('storyPlan.wave', { n: w + 1 })}
                onDragOver={(e) => canEdit && e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  const key = e.dataTransfer.getData('text/plain')
                  if (key) move(key, w)
                  setDragging(null)
                }}
              >
                <CardHeader
                  title={
                    isNew ? (
                      <span className="flex items-center gap-1.5">
                        <Plus size={14} /> {t('storyPlan.newWave')}
                      </span>
                    ) : (
                      t('storyPlan.wave', { n: w + 1 })
                    )
                  }
                  subtitle={
                    isNew
                      ? t('storyPlan.newWaveHint')
                      : t('storyPlan.waveSummary', {
                          count: items.length,
                          points: items.reduce((a, s) => a + s.estimate, 0),
                          rules: new Set(items.flatMap((s) => s.links)).size,
                        })
                  }
                />
                <ul className="space-y-2 p-3">
                  {items.map((s, i) => {
                    const own = problems.filter((p) => p.story === s.key)
                    const hard = plan.errors.some((p) => p.story === s.key)
                    const d = diff.find((x) => x.story === s.key)
                    const deps = dependenciesOf(s)
                    return (
                      <li
                        key={s.key}
                        draggable={canEdit}
                        onDragStart={(e) => {
                          e.dataTransfer.setData('text/plain', s.key)
                          setDragging(s.key)
                        }}
                        onDragEnd={() => setDragging(null)}
                        className={cn(
                          'rounded-md border bg-surface p-2.5 text-sm',
                          hard ? 'border-critical' : own.length ? 'border-warning' : 'border-border',
                          canEdit && 'cursor-grab',
                          dragging === s.key && 'opacity-50',
                        )}
                      >
                        <div className="flex items-center gap-1.5">
                          {canEdit && <GripVertical size={14} className="text-muted" />}
                          <span className="font-mono text-xs text-info-ink">{s.key}</span>
                          <Badge tone={storyStatusTone(s.status)} className="ml-auto">
                            {t(`stories.status.${s.status}`, { defaultValue: s.status })}
                          </Badge>
                        </div>
                        <div className="mt-1 text-text">{s.title}</div>
                        <div className="mt-1 flex flex-wrap gap-x-2 text-xs text-muted">
                          <span>{s.priority}</span>
                          <span>{t('stories.points', { count: s.estimate })}</span>
                          {deps.length > 0 && (
                            <span>{t('storyPlan.needs', { ids: deps.map((x) => x.on).join(', ') })}</span>
                          )}
                        </div>
                        {showDiff && d && (
                          <div className="mt-1 text-xs text-info-ink">
                            {d.from === -1
                              ? t('storyPlan.notInSuggestion')
                              : t('storyPlan.diff', { from: d.from + 1, to: d.to + 1 })}
                          </div>
                        )}
                        {own.map((p) => (
                          <div
                            key={`${p.code}${p.on}`}
                            className={cn(
                              'mt-1 flex items-start gap-1 text-xs',
                              p.code === 'soft_dependency' ? 'text-warning-ink' : 'text-critical-ink',
                            )}
                          >
                            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                            <ProblemText problem={p} />
                          </div>
                        ))}
                        {canEdit && (
                          <div className="mt-2 flex gap-1">
                            <IconBtn
                              label={t('storyPlan.prevWaveOf', { id: s.key })}
                              disabled={w === 0 || busy}
                              onClick={() => move(s.key, w - 1)}
                              icon={<ArrowLeft size={12} />}
                            />
                            <IconBtn
                              label={t('storyPlan.nextWaveOf', { id: s.key })}
                              disabled={busy || (w === plan.waves.length - 1 && items.length === 1)}
                              onClick={() => move(s.key, w + 1)}
                              icon={<ArrowRight size={12} />}
                            />
                            <IconBtn
                              label={t('storyPlan.upOf', { id: s.key })}
                              disabled={i === 0 || busy}
                              onClick={() => move(s.key, w, i - 1)}
                              icon={<ArrowUp size={12} />}
                            />
                            <IconBtn
                              label={t('storyPlan.downOf', { id: s.key })}
                              disabled={i === items.length - 1 || busy}
                              onClick={() => move(s.key, w, i + 1)}
                              icon={<ArrowDown size={12} />}
                            />
                          </div>
                        )}
                      </li>
                    )
                  })}
                  {items.length === 0 && (
                    <li className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted">
                      {t('storyPlan.dropHere')}
                    </li>
                  )}
                </ul>
              </div>
            </Card>
          )
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('storyPlan.issues')} subtitle={t('storyPlan.issuesHint')} />
          <CardBody className="space-y-1.5 text-sm">
            {problems.length === 0 ? (
              <p className="text-good-ink">{t('storyPlan.noIssues')}</p>
            ) : (
              problems.map((p) => (
                <p
                  key={`${p.code}${p.story}${p.on}`}
                  className={p.code === 'soft_dependency' ? 'text-warning-ink' : 'text-critical-ink'}
                >
                  <b className="font-mono">{p.story}</b> → <ProblemText problem={p} />
                </p>
              ))
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('storyPlan.diffTitle')} subtitle={t('storyPlan.diffHint')} />
          <CardBody className="space-y-2 text-sm">
            {diff.length === 0 ? (
              <p className="text-text-2">{t('storyPlan.sameAsSuggested')}</p>
            ) : (
              diff.map((d) => (
                <p key={d.story} className="text-text-2">
                  <b className="font-mono text-text">{d.story}</b>{' '}
                  {d.from === -1
                    ? t('storyPlan.notInSuggestion')
                    : t('storyPlan.diff', { from: d.from + 1, to: d.to + 1 })}
                </p>
              ))
            )}
            <div className="border-t border-border pt-2">
              <div className="mb-1 text-xs font-medium text-muted">{t('storyPlan.suggested')}</div>
              <ol className="space-y-0.5 text-xs text-text-2">
                {plan.suggested.map((w, i) => (
                  <li key={i}>
                    <span className="text-muted">{t('storyPlan.wave', { n: i + 1 })}:</span>{' '}
                    <span className="font-mono">{w.join(', ')}</span>
                  </li>
                ))}
              </ol>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

/** A plan problem of the server, translated by code (its English message as the fallback and the detail). */
function ProblemText({ problem }: { problem: PlanProblem }) {
  const { t } = useTranslation()
  switch (problem.code) {
    case 'hard_dependency':
      return (
        <span title={problem.message}>
          {t('storyPlan.hardIssue', { story: problem.story, dependency: problem.on })}
        </span>
      )
    case 'soft_dependency':
      return <span title={problem.message}>{t('storyPlan.softIssue', { dependency: problem.on })}</span>
    default:
      return (
        <span title={problem.message}>
          {t(`storyPlan.problem.${camelKey(problem.code)}`, {
            defaultValue: problem.message,
            story: problem.story,
            on: problem.on,
          })}
        </span>
      )
  }
}
