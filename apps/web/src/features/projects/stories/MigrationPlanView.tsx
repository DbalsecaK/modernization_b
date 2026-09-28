import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Ban, GripVertical, Plus, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { UserStory } from '@/mocks/data'
import { moveStory, planDiff, validatePlan, type PlanIssue } from '@/lib/migrationPlan'
import { Badge, Button, Card, CardBody, CardHeader, Toggle } from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'
import { Notice } from '../NewProjectWizard'
import { can, resetPlan, setPlan, suggestedFor, useStories } from './store'
import { storyStatusTone } from './UserStoriesView'
import { RoleSwitch } from './RoleSwitch'

// Migration plan by waves (spec 7.7). The platform suggests it from the dependencies in the knowledge graph;
// people reorder it and every move is validated by deterministic code: hard dependencies block, soft ones warn.

export function MigrationPlanView() {
  const { t } = useTranslation()
  const { stories, plan, role, approved } = useStories()
  const [dragging, setDragging] = useState<string | null>(null)
  const [showDiff, setShowDiff] = useState(true)
  const [rejected, setRejected] = useState<PlanIssue[]>([])
  const editable = can.editPlan(role)
  const live = stories.filter((s) => s.status !== 'discarded' && s.status !== 'merged')
  const byId = new Map(stories.map((s) => [s.id, s]))
  const suggested = suggestedFor(stories)
  const issues = validatePlan(plan, live)
  const diff = planDiff(suggested, plan)
  const waves = [...plan, []]

  function move(id: string, toWave: number, index?: number) {
    if (!editable) return
    const r = moveStory(plan, live, id, toWave, index)
    if (!r.accepted) {
      // The rejection card explains it (toasts are for confirmations only).
      setRejected(r.newIssues.filter((i) => i.kind === 'hard'))
      return
    }
    setRejected([])
    setPlan(r.plan.filter((w) => w.length > 0))
    if (r.newIssues.length > 0) toast(t('storyPlan.movedWithWarning', { id }))
    else if (approved) toast(t('storyPlan.changeAfterC1'))
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Notice tone="info">{t('storyPlan.hint')}</Notice>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <RoleSwitch />
          <Toggle checked={showDiff} onChange={setShowDiff} label={t('storyPlan.showDiff')} />
          <Button size="sm" disabled={!editable || diff.length === 0} onClick={() => (resetPlan(), setRejected([]), toast(t('storyPlan.resetDone')))}>
            <RotateCcw size={14} /> {t('storyPlan.reset')}
          </Button>
        </div>
      </div>
      {!editable && <Notice tone="warning">{t('storyPlan.readOnly')}</Notice>}

      {rejected.length > 0 && (
        <Card className="border-critical">
          <CardHeader title={<span className="flex items-center gap-1.5 text-critical-ink"><Ban size={14} /> {t('storyPlan.rejected', { id: rejected[0].story })}</span>} />
          <CardBody className="space-y-1 text-sm">
            {rejected.map((i) => (
              <p key={i.story + i.dependency} className="text-text-2">
                {t('storyPlan.hardIssue', { story: i.story, dependency: i.dependency })} <span className="text-muted">{i.reason}</span>
              </p>
            ))}
          </CardBody>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {waves.map((wave, w) => {
          const items = wave.map((id) => byId.get(id)).filter(Boolean) as UserStory[]
          const isNew = w === plan.length
          return (
            <Card
              key={w}
              className={cn('flex flex-col', dragging && 'border-dashed', isNew && 'opacity-80')}
            >
              <div
                className="flex-1"
                onDragOver={(e) => editable && e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  const id = e.dataTransfer.getData('text/plain')
                  if (id) move(id, w)
                  setDragging(null)
                }}
              >
                <CardHeader
                  title={isNew ? <span className="flex items-center gap-1.5"><Plus size={14} /> {t('storyPlan.newWave')}</span> : t('storyPlan.wave', { n: w + 1 })}
                  subtitle={
                    isNew
                      ? t('storyPlan.newWaveHint')
                      : t('storyPlan.waveSummary', { count: items.length, points: items.reduce((a, s) => a + s.points, 0), rules: new Set(items.flatMap((s) => s.rules)).size })
                  }
                />
                <ul className="space-y-2 p-3">
                  {items.map((s, i) => {
                    const own = issues.filter((x) => x.story === s.id)
                    const d = diff.find((x) => x.story === s.id)
                    return (
                      <li
                        key={s.id}
                        draggable={editable}
                        onDragStart={(e) => {
                          e.dataTransfer.setData('text/plain', s.id)
                          setDragging(s.id)
                        }}
                        onDragEnd={() => setDragging(null)}
                        className={cn(
                          'rounded-md border bg-surface p-2.5 text-sm',
                          own.some((x) => x.kind === 'hard') ? 'border-critical' : own.length ? 'border-warning' : 'border-border',
                          editable && 'cursor-grab',
                          dragging === s.id && 'opacity-50',
                        )}
                      >
                        <div className="flex items-center gap-1.5">
                          {editable && <GripVertical size={14} className="text-muted" />}
                          <span className="font-mono text-xs text-info">{s.id}</span>
                          <Badge tone={storyStatusTone[s.status]} className="ml-auto">
                            {t(`stories.status.${s.status}`)}
                          </Badge>
                        </div>
                        <div className="mt-1 text-text">{s.title}</div>
                        <div className="mt-1 flex flex-wrap gap-x-2 text-xs text-muted">
                          <span>{s.priority}</span>
                          <span>{t('stories.points', { count: s.points })}</span>
                          {s.dependsOn.length > 0 && <span>{t('storyPlan.needs', { ids: s.dependsOn.map((x) => x.story).join(', ') })}</span>}
                        </div>
                        {showDiff && d && (
                          <div className="mt-1 text-xs text-info">
                            {d.from === -1 ? t('storyPlan.notInSuggestion') : t('storyPlan.diff', { from: d.from + 1, to: d.to + 1 })}
                          </div>
                        )}
                        {own.map((x) => (
                          <div key={x.dependency} className={cn('mt-1 flex items-start gap-1 text-xs', x.kind === 'hard' ? 'text-critical-ink' : 'text-warning-ink')}>
                            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                            {x.problem === 'missing'
                              ? t('storyPlan.missing', { dependency: x.dependency })
                              : x.kind === 'hard'
                                ? t('storyPlan.hardIssue', { story: x.story, dependency: x.dependency })
                                : t('storyPlan.softIssue', { dependency: x.dependency })}
                          </div>
                        ))}
                        {editable && (
                          <div className="mt-2 flex gap-1">
                            <IconBtn label={t('storyPlan.prevWave')} disabled={w === 0} onClick={() => move(s.id, w - 1)} icon={<ArrowLeft size={12} />} />
                            <IconBtn label={t('storyPlan.nextWave')} onClick={() => move(s.id, w + 1)} icon={<ArrowRight size={12} />} />
                            <IconBtn label={t('storyPlan.up')} disabled={i === 0} onClick={() => move(s.id, w, i - 1)} icon={<ArrowUp size={12} />} />
                            <IconBtn label={t('storyPlan.down')} disabled={i === items.length - 1} onClick={() => move(s.id, w, i + 1)} icon={<ArrowDown size={12} />} />
                          </div>
                        )}
                      </li>
                    )
                  })}
                  {items.length === 0 && <li className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted">{t('storyPlan.dropHere')}</li>}
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
            {issues.length === 0 ? (
              <p className="text-good-ink">{t('storyPlan.noIssues')}</p>
            ) : (
              issues.map((x) => (
                <p key={x.story + x.dependency} className={x.kind === 'hard' ? 'text-critical-ink' : 'text-warning-ink'}>
                  <b className="font-mono">{x.story}</b> →{' '}
                  {x.problem === 'missing' ? t('storyPlan.missing', { dependency: x.dependency }) : x.kind === 'hard' ? t('storyPlan.hardIssue', { story: x.story, dependency: x.dependency }) : t('storyPlan.softIssue', { dependency: x.dependency })}{' '}
                  <span className="text-muted">{x.reason}</span>
                </p>
              ))
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('storyPlan.diffTitle')} subtitle={t('storyPlan.diffHint')} />
          <CardBody className="space-y-1 text-sm">
            {diff.length === 0 ? (
              <p className="text-text-2">{t('storyPlan.sameAsSuggested')}</p>
            ) : (
              diff.map((d) => (
                <p key={d.story} className="text-text-2">
                  <b className="font-mono text-text">{d.story}</b> {d.from === -1 ? t('storyPlan.notInSuggestion') : t('storyPlan.diff', { from: d.from + 1, to: d.to + 1 })}
                </p>
              ))
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function IconBtn({ label, icon, onClick, disabled }: { label: string; icon: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={label} title={label} className="rounded border border-border p-1 text-muted hover:bg-surface-2 hover:text-text disabled:opacity-40">
      {icon}
    </button>
  )
}
