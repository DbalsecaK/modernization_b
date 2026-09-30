import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  CheckCircle2,
  GitMerge,
  History,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Scissors,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import {
  useAddDependency,
  useGherkin,
  useRemoveDependency,
  useRestoreStory,
  useStoryVersions,
  type Coverage,
  type StoryOut,
} from '@/api/spec'
import { Badge, Button, Card, CardBody, CardHeader, Code, Field, Input, Select } from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'
import { Notice } from '../../NewProjectWizard'
import {
  dependenciesOf,
  groupByFeature,
  isActive,
  priorityTone,
  problemsByCriterion,
  storyStatusTone,
  waveIndex,
  type RuleView,
  type Waves,
} from './model'
import { errorText, Gap, GherkinProblems, Links, ListButton, Meta } from './shared'
import { DiscardForm, MergeForm, SplitForm, StoryForm } from './StoryForms'

const FILTER_STATUSES = ['draft', 'review', 'question', 'approved', 'discarded', 'merged'] as const

// User stories to build (spec 7.7), reviewed and approved at gate C1 with the plan. Every change is a new version on
// the server, audited; acceptance criteria are validated by the server's Gherkin validator, live while typing.
export function StoriesView({
  projectId,
  stories,
  rules,
  coverage,
  waves,
  canEdit,
  canEditPlan,
  selected,
  onSelect,
}: {
  projectId: string
  stories: StoryOut[]
  rules: RuleView[]
  coverage: Coverage | undefined
  waves: Waves
  canEdit: boolean
  canEditPlan: boolean
  selected: string | null
  onSelect: (key: string) => void
}) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<'all' | string>('all')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<StoryOut | 'new' | null>(null)
  const [splitting, setSplitting] = useState(false)
  const [merging, setMerging] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const live = stories.filter(isActive)
  const list = useMemo(
    () =>
      stories.filter(
        (s) =>
          (status === 'all' ? s.status !== 'merged' : s.status === status) &&
          `${s.key} ${s.title}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [stories, status, query],
  )
  const story = stories.find((s) => s.key === selected) ?? list[0] ?? null
  const count = (st: string) => stories.filter((s) => s.status === st).length
  const features = [...new Set(stories.map((s) => s.feature).filter(Boolean))]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge>{t('stories.total', { count: live.length })}</Badge>
          <Badge tone="good">
            {t('stories.status.approved')}: {count('approved')}
          </Badge>
          <Badge tone="info">
            {t('stories.status.review')}: {count('review')}
          </Badge>
          <Badge tone="warning">
            {t('stories.status.question')}: {count('question')}
          </Badge>
          <Badge>
            {t('stories.status.draft')}: {count('draft')}
          </Badge>
          <Badge>{t('stories.points', { count: live.reduce((a, s) => a + s.estimate, 0) })}</Badge>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {!canEdit && <span className="text-xs text-muted">{t('stories.readOnly')}</span>}
          {canEdit && (
            <Button size="sm" onClick={() => setEditing('new')}>
              <Plus size={14} /> {t('stories.new')}
            </Button>
          )}
        </div>
      </div>

      {coverage &&
        (coverage.gaps.length > 0 || coverage.untracedStories.length > 0 || coverage.outOfScope.length > 0) && (
          <Card>
            <CardHeader title={t('stories.coverage')} subtitle={t('stories.coverageHint')} />
            <CardBody className="space-y-1.5 text-sm">
              {coverage.gaps.length > 0 && <Gap label={t('stories.uncoveredRules')} items={coverage.gaps} />}
              {coverage.untracedStories.length > 0 && (
                <Gap label={t('stories.untraced')} items={coverage.untracedStories} />
              )}
              {coverage.outOfScope.length > 0 && (
                <Gap label={t('stories.outOfScope')} items={coverage.outOfScope} tone="neutral" />
              )}
            </CardBody>
          </Card>
        )}

      {stories.length === 0 ? (
        <Card>
          <CardBody className="text-center text-sm text-muted">
            <p className="font-medium text-text">{t('stories.noStories')}</p>
            <p className="mt-1">{t('stories.noStoriesHint')}</p>
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <Card>
            <div className="flex gap-2 border-b border-border p-3">
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('stories.search')}
                aria-label={t('stories.search')}
                className="h-9"
              />
              <div className="w-40 shrink-0">
                <Select
                  className="h-9"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  aria-label={t('stories.filterStatus')}
                >
                  <option value="all">{t('stories.allStatuses')}</option>
                  {FILTER_STATUSES.map((st) => (
                    <option key={st} value={st}>
                      {t(`stories.status.${st}`)}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            {list.length === 0 && <p className="px-4 py-6 text-center text-sm text-muted">{t('stories.noMatch')}</p>}
            {groupByFeature(list).map((group) => (
              <div key={group.feature || '—'}>
                <div className="bg-surface-2 px-4 py-1.5 text-xs font-semibold text-text-2">
                  {group.feature || t('stories.noFeature')}
                </div>
                <ul className="divide-y divide-border">
                  {group.items.map((s) => (
                    <li key={s.key}>
                      <ListButton selected={story?.key === s.key} onClick={() => onSelect(s.key)}>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-info-ink">{s.key}</span>
                          {s.origin === 'person' && (
                            <UserRound size={12} className="text-muted" aria-label={t('stories.origin.person')} />
                          )}
                          {!s.traced && isActive(s) && (
                            <AlertTriangle size={12} className="text-warning" aria-label={t('stories.untraced')} />
                          )}
                          <Badge tone={storyStatusTone(s.status)} className="ml-auto">
                            {t(`stories.status.${s.status}`, { defaultValue: s.status })}
                          </Badge>
                        </div>
                        <div className={cn('mt-0.5 text-sm text-text', !isActive(s) && 'line-through opacity-60')}>
                          {s.title}
                        </div>
                        <div className="text-xs text-muted">
                          {s.priority} · {t('stories.points', { count: s.estimate })} · {waveLabel(waves, s.key, t)}
                        </div>
                      </ListButton>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </Card>

          {story && (
            <div className="space-y-4">
              <StoryDetail
                projectId={projectId}
                story={story}
                stories={stories}
                waves={waves}
                canEdit={canEdit}
                canEditPlan={canEditPlan}
                onSelect={onSelect}
                onEdit={() => setEditing(story)}
                onSplit={() => setSplitting(true)}
                onMerge={() => setMerging(true)}
                onDiscard={() => setDiscarding(true)}
              />
              <StoryHistory projectId={projectId} storyKey={story.key} />
            </div>
          )}
        </div>
      )}

      {editing && (
        <StoryForm
          key={editing === 'new' ? 'new' : editing.key}
          projectId={projectId}
          story={editing === 'new' ? null : editing}
          rules={rules}
          features={features}
          onClose={() => setEditing(null)}
          onSaved={onSelect}
        />
      )}
      {splitting && story && (
        <SplitForm projectId={projectId} story={story} onClose={() => setSplitting(false)} onDone={onSelect} />
      )}
      {merging && story && (
        <MergeForm
          projectId={projectId}
          story={story}
          stories={live.filter((s) => s.key !== story.key)}
          onClose={() => setMerging(false)}
        />
      )}
      {discarding && story && (
        <DiscardForm projectId={projectId} story={story} stories={stories} onClose={() => setDiscarding(false)} />
      )}
    </div>
  )
}

export function waveLabel(waves: Waves, key: string, t: (k: string, o?: Record<string, unknown>) => string) {
  const w = waveIndex(waves, key)
  return w === -1 ? t('storyPlan.notPlanned') : t('storyPlan.wave', { n: w + 1 })
}

function StoryDetail({
  projectId,
  story,
  stories,
  waves,
  canEdit,
  canEditPlan,
  onSelect,
  onEdit,
  onSplit,
  onMerge,
  onDiscard,
}: {
  projectId: string
  story: StoryOut
  stories: StoryOut[]
  waves: Waves
  canEdit: boolean
  canEditPlan: boolean
  onSelect: (key: string) => void
  onEdit: () => void
  onSplit: () => void
  onMerge: () => void
  onDiscard: () => void
}) {
  const { t } = useTranslation()
  const restore = useRestoreStory(projectId)
  const gherkin = useGherkin(story.criteria)
  const problems = problemsByCriterion(gherkin.data?.problems ?? [])
  const active = isActive(story)

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-info-ink">{story.key}</span> {story.title}
            <Badge tone={storyStatusTone(story.status)}>
              {t(`stories.status.${story.status}`, { defaultValue: story.status })}
            </Badge>
          </span>
        }
        subtitle={t('stories.meta', {
          feature: story.feature || t('stories.noFeature'),
          version: story.version,
          wave: waveLabel(waves, story.key, t),
        })}
      />
      <CardBody className="space-y-4 text-sm">
        {story.narrative && <p className="whitespace-pre-line text-text">{story.narrative}</p>}
        {story.status === 'discarded' && (
          <Notice tone="warning">
            {t(story.outOfScope ? 'stories.discardedOos' : 'stories.discardedMsg', { reason: story.reason ?? '' })}
          </Notice>
        )}
        {story.status === 'merged' && <Notice tone="info">{t('stories.mergedMsg', { id: story.mergedInto })}</Notice>}

        <div>
          <div className="mb-1 text-xs font-medium text-muted">{t('stories.criteria')}</div>
          {story.criteria.length === 0 ? (
            <Notice tone="warning">{t('stories.noCriteria')}</Notice>
          ) : (
            <div className="space-y-2">
              {story.criteria.map((c, i) => {
                const own = problems.get(i) ?? []
                return (
                  <div key={i}>
                    <Code className={cn('whitespace-pre-wrap', own.length > 0 && 'ring-1 ring-critical')}>{c}</Code>
                    {gherkin.data &&
                      (own.length === 0 ? (
                        <div className="mt-1 flex items-center gap-1 text-xs text-good-ink">
                          <CheckCircle2 size={12} /> {t('gherkin.valid')}
                        </div>
                      ) : (
                        <GherkinProblems problems={own} />
                      ))}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <Links label={t('stories.rules')} items={story.links} />
        {!story.traced && active && <Notice tone="warning">{t('stories.untracedHint')}</Notice>}

        <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <Meta
            label={t('stories.originLabel')}
            value={t(`stories.origin.${story.origin}`, { defaultValue: story.origin })}
          />
          <Meta
            label={t('stories.priority')}
            value={<Badge tone={priorityTone(story.priority)}>{story.priority}</Badge>}
          />
          <Meta label={t('stories.estimate')} value={t('stories.points', { count: story.estimate })} />
          <Meta label={t('stories.wave')} value={waveLabel(waves, story.key, t)} />
        </dl>

        <Dependencies
          projectId={projectId}
          story={story}
          stories={stories}
          canEdit={canEditPlan && active}
          onSelect={onSelect}
        />

        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          {active ? (
            <>
              <Button size="sm" disabled={!canEdit} onClick={onEdit}>
                <Pencil size={14} /> {t('stories.edit')}
              </Button>
              <Button size="sm" disabled={!canEdit || story.criteria.length + story.links.length < 2} onClick={onSplit}>
                <Scissors size={14} /> {t('stories.split')}
              </Button>
              <Button size="sm" disabled={!canEdit} onClick={onMerge}>
                <GitMerge size={14} /> {t('stories.merge')}
              </Button>
              <Button size="sm" variant="ghost" disabled={!canEdit} onClick={onDiscard}>
                <Trash2 size={14} /> {t('stories.discard')}
              </Button>
            </>
          ) : (
            story.status === 'discarded' && (
              <Button
                size="sm"
                disabled={!canEdit || restore.isPending}
                onClick={() =>
                  restore.mutate(story.key, {
                    onSuccess: () => toast(t('stories.restored')),
                    onError: (e) => toast(errorText(e, t('common.error'))),
                  })
                }
              >
                <RotateCcw size={14} /> {t('stories.restore')}
              </Button>
            )
          )}
          {!canEdit && <span className="self-center text-xs text-muted">{t('stories.readOnly')}</span>}
        </div>
      </CardBody>
    </Card>
  )
}

function Dependencies({
  projectId,
  story,
  stories,
  canEdit,
  onSelect,
}: {
  projectId: string
  story: StoryOut
  stories: StoryOut[]
  canEdit: boolean
  onSelect: (key: string) => void
}) {
  const { t } = useTranslation()
  const deps = dependenciesOf(story)
  const add = useAddDependency(projectId)
  const remove = useRemoveDependency(projectId)
  const candidates = stories.filter((s) => isActive(s) && s.key !== story.key && !deps.some((d) => d.on === s.key))
  const [on, setOn] = useState('')
  const [strength, setStrength] = useState<'hard' | 'soft'>('soft')
  const [reason, setReason] = useState('')
  const target = candidates.some((c) => c.key === on) ? on : (candidates[0]?.key ?? '')

  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted">{t('stories.dependsOn')}</div>
      {deps.length === 0 ? (
        <span className="text-xs text-muted">{t('stories.noDependencies')}</span>
      ) : (
        <ul className="space-y-1">
          {deps.map((d) => (
            <li key={d.on} className="flex flex-wrap items-center gap-2 text-xs">
              <button className="font-mono text-info-ink hover:underline" onClick={() => onSelect(d.on)}>
                {d.on}
              </button>
              <Badge tone={d.strength === 'hard' ? 'critical' : 'neutral'}>{t(`storyPlan.kind.${d.strength}`)}</Badge>
              <span className="text-text-2">{d.reason}</span>
              {canEdit && (
                <button
                  className="ml-auto rounded p-0.5 text-muted hover:bg-surface-2 hover:text-text disabled:opacity-40"
                  aria-label={t('stories.removeDependency', { id: d.on })}
                  title={t('stories.removeDependency', { id: d.on })}
                  disabled={remove.isPending}
                  onClick={() =>
                    remove.mutate(
                      { key: story.key, on: d.on },
                      {
                        onSuccess: () => toast(t('stories.depRemoved')),
                        onError: (e) => toast(errorText(e, t('common.error'))),
                      },
                    )
                  }
                >
                  <X size={12} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && candidates.length > 0 && (
        <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_120px_1fr_auto] sm:items-end">
          <Field label={t('stories.depStory')}>
            <Select className="h-8" value={target} onChange={(e) => setOn(e.target.value)}>
              {candidates.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.key} · {c.title}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('stories.depKind')}>
            <Select className="h-8" value={strength} onChange={(e) => setStrength(e.target.value as 'hard' | 'soft')}>
              <option value="hard">{t('storyPlan.kind.hard')}</option>
              <option value="soft">{t('storyPlan.kind.soft')}</option>
            </Select>
          </Field>
          <Field label={t('stories.depReason')}>
            <Input className="h-8" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
          </Field>
          <Button
            size="sm"
            disabled={!target || add.isPending}
            onClick={() =>
              add.mutate(
                { key: story.key, body: { on: target, strength, reason: reason.trim() } },
                {
                  onSuccess: () => {
                    setReason('')
                    toast(t('stories.depAdded'))
                  },
                  onError: (e) => toast(errorText(e, t('common.error'))),
                },
              )
            }
          >
            {add.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}{' '}
            {t('stories.addDependency')}
          </Button>
        </div>
      )}
      <p className="mt-1 text-xs text-muted">{t('stories.dependsOnHint')}</p>
    </div>
  )
}

function StoryHistory({ projectId, storyKey }: { projectId: string; storyKey: string }) {
  const { t } = useTranslation()
  const versions = useStoryVersions(projectId, storyKey)
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <History size={14} /> {t('stories.history')}
          </span>
        }
      />
      <ul className="divide-y divide-border">
        {versions.isLoading && <li className="px-5 py-3 text-xs text-muted">{t('common.loading')}</li>}
        {versions.data?.length === 0 && <li className="px-5 py-3 text-xs text-muted">{t('stories.noHistory')}</li>}
        {(versions.data ?? []).map((v) => (
          <li key={v.version} className="flex flex-wrap gap-x-2 px-5 py-2 text-xs">
            <span className="font-mono text-muted">v{v.version}</span>
            <span className="text-muted tabular">{formatDateTime(v.createdAt)}</span>
            <span className="font-medium text-text">{v.createdByName ?? t('stories.byPlatform')}</span>
            <span className="text-text-2">{t(`stories.action.${v.action}`, { defaultValue: v.action })}</span>
            {v.reason && <span className="text-muted">· {v.reason}</span>}
          </li>
        ))}
      </ul>
    </Card>
  )
}
