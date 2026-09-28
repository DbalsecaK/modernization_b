import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  GitMerge,
  History,
  Link2,
  Pencil,
  Plus,
  RotateCcw,
  Scissors,
  Trash2,
  UserRound,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import {
  contracts,
  rules,
  screenSpecs,
  storyFeatures,
  storySuggestions,
  type StoryStatus,
  type UserStory,
} from '@/mocks/data'
import { Badge, Button, Card, CardBody, CardHeader, Code, Field, Input, Select } from '@/components/ui/primitives'
import { CheckboxGroup, Drawer, Textarea, toast } from '@/components/ui/overlay'
import { Notice } from '../NewProjectWizard'
import { validatePlan } from '@/lib/migrationPlan'
import { splitScenarios, validateCriteria, type GherkinIssue } from '@/lib/gherkin'
import {
  approveC1,
  can,
  discardStory,
  dismissSuggestion,
  mergeStories,
  nextStoryId,
  restoreStory,
  saveStory,
  splitStory,
  useStories,
} from './store'
import { RoleSwitch } from './RoleSwitch'

// User stories to build, reviewed and approved at gate C1 before the migration starts (spec 7.7).

export const storyStatusTone: Record<StoryStatus, 'good' | 'info' | 'warning' | 'neutral' | 'critical'> = {
  approved: 'good',
  inReview: 'info',
  question: 'warning',
  draft: 'neutral',
  discarded: 'critical',
  merged: 'neutral',
}

const active = (s: UserStory) => s.status !== 'discarded' && s.status !== 'merged'
const traced = (s: UserStory) => s.rules.length + s.screens.length + s.contracts.length + s.nodes.length > 0

export function UserStoriesView() {
  const { t } = useTranslation()
  const { stories, plan, history, approved, role, dismissed } = useStories()
  const [selected, setSelected] = useState(stories[0].id)
  const [status, setStatus] = useState<'all' | StoryStatus>('all')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<UserStory | null>(null)
  const [splitting, setSplitting] = useState(false)
  const [merging, setMerging] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const story = stories.find((s) => s.id === selected) ?? stories[0]
  const editable = can.editStories(role)

  const live = stories.filter(active)
  // Coverage: every rule, screen and contract of the specification must be in at least one active story.
  const uncovered = {
    rules: rules.filter((r) => !live.some((s) => s.rules.includes(r.id))).map((r) => r.id),
    screens: screenSpecs.filter((x) => !live.some((s) => s.screens.includes(x.id))).map((x) => x.id),
    contracts: contracts.filter((c) => !live.some((s) => s.contracts.includes(c.id))).map((c) => c.id),
  }
  const outOfScope = stories.filter((s) => s.outOfScope)
  const untraced = live.filter((s) => !traced(s))
  const noCriteria = live.filter((s) => s.criteria.length === 0)
  const questions = live.filter((s) => s.status === 'question')
  const invalid = live.filter((s) => validateCriteria(s.criteria).length > 0)
  const hardIssues = validatePlan(plan, live).filter((i) => i.kind === 'hard')
  const blockers = questions.length + noCriteria.length + invalid.length + hardIssues.length
  const coverageGaps = uncovered.rules.length + uncovered.screens.length + uncovered.contracts.length

  const list = stories.filter(
    (s) =>
      (status === 'all' ? s.status !== 'merged' : s.status === status) &&
      `${s.id} ${s.title}`.toLowerCase().includes(query.toLowerCase()),
  )
  const counts = (st: StoryStatus) => stories.filter((s) => s.status === st).length
  const suggestions = storySuggestions.filter((g) => g.story === story.id && !dismissed.includes(g.id))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge>{t('stories.total', { count: live.length })}</Badge>
          <Badge tone="good">
            {t('stories.status.approved')}: {counts('approved')}
          </Badge>
          <Badge tone="info">
            {t('stories.status.inReview')}: {counts('inReview')}
          </Badge>
          <Badge tone="warning">
            {t('stories.status.question')}: {counts('question')}
          </Badge>
          <Badge>
            {t('stories.status.draft')}: {counts('draft')}
          </Badge>
          <Badge>{t('stories.points', { count: live.reduce((a, s) => a + s.points, 0) })}</Badge>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <RoleSwitch />
          <Button size="sm" disabled={!editable} onClick={() => setEditing(blankStory(nextStoryId()))}>
            <Plus size={14} /> {t('stories.new')}
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={!editable || approved || blockers > 0}
            title={blockers > 0 ? t('stories.approveBlocked') : undefined}
            onClick={() => {
              approveC1()
              toast(t('stories.approvedToast'))
            }}
          >
            <CheckCircle2 size={14} /> {approved ? t('stories.approvedC1') : t('stories.approveC1')}
          </Button>
        </div>
      </div>

      {approved ? (
        <Notice tone="info">{t('stories.afterC1')}</Notice>
      ) : (
        <Notice tone={blockers > 0 ? 'warning' : 'info'}>
          {blockers > 0
            ? t('stories.blockers', {
                questions: questions.length,
                criteria: noCriteria.length,
                invalid: invalid.length,
                plan: hardIssues.length,
              })
            : t('stories.readyToApprove')}
        </Notice>
      )}
      {(coverageGaps > 0 || untraced.length > 0 || outOfScope.length > 0) && (
        <Card>
          <CardHeader title={t('stories.coverage')} subtitle={t('stories.coverageHint')} />
          <CardBody className="space-y-1.5 text-sm">
            {uncovered.rules.length > 0 && <Gap label={t('stories.uncoveredRules')} items={uncovered.rules} />}
            {uncovered.screens.length > 0 && <Gap label={t('stories.uncoveredScreens')} items={uncovered.screens} />}
            {uncovered.contracts.length > 0 && (
              <Gap label={t('stories.uncoveredContracts')} items={uncovered.contracts} />
            )}
            {untraced.length > 0 && <Gap label={t('stories.untraced')} items={untraced.map((s) => s.id)} />}
            {outOfScope.length > 0 && (
              <Gap label={t('stories.outOfScope')} items={outOfScope.map((s) => s.id)} tone="neutral" />
            )}
          </CardBody>
        </Card>
      )}

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
                onChange={(e) => setStatus(e.target.value as typeof status)}
                aria-label={t('stories.filterStatus')}
              >
                <option value="all">{t('stories.allStatuses')}</option>
                {(['draft', 'inReview', 'question', 'approved', 'discarded'] as const).map((st) => (
                  <option key={st} value={st}>
                    {t(`stories.status.${st}`)}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          {storyFeatures.map((f) => {
            const items = list.filter((s) => s.feature === f.id)
            if (items.length === 0) return null
            return (
              <div key={f.id}>
                <div className="bg-surface-2 px-4 py-1.5 text-xs font-semibold text-text-2">
                  <span className="font-mono text-muted">{f.id}</span> · {f.name}
                </div>
                <ul className="divide-y divide-border">
                  {items.map((s) => (
                    <li key={s.id}>
                      <button
                        onClick={() => setSelected(s.id)}
                        className={cn(
                          'w-full px-4 py-2.5 text-left hover:bg-surface-2',
                          selected === s.id && 'bg-surface-2',
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-info">{s.id}</span>
                          {s.origin === 'user' && (
                            <UserRound size={12} className="text-muted" aria-label={t('stories.origin.user')} />
                          )}
                          {!traced(s) && active(s) && (
                            <AlertTriangle size={12} className="text-warning" aria-label={t('stories.untraced')} />
                          )}
                          {active(s) && validateCriteria(s.criteria).length > 0 && (
                            <AlertTriangle size={12} className="text-critical" aria-label={t('gherkin.invalidStory')} />
                          )}
                          <Badge tone={storyStatusTone[s.status]} className="ml-auto">
                            {t(`stories.status.${s.status}`)}
                          </Badge>
                        </div>
                        <div className={cn('mt-0.5 text-sm text-text', !active(s) && 'line-through opacity-60')}>
                          {s.title}
                        </div>
                        <div className="text-xs text-muted">
                          {s.priority} · {t('stories.points', { count: s.points })} · {waveLabel(plan, s.id, t)}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader
              title={
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-info">{story.id}</span> {story.title}
                  <Badge tone={storyStatusTone[story.status]}>{t(`stories.status.${story.status}`)}</Badge>
                </span>
              }
              subtitle={t('stories.meta', {
                feature: storyFeatures.find((f) => f.id === story.feature)?.name,
                version: story.version,
                wave: waveLabel(plan, story.id, t),
              })}
            />
            <CardBody className="space-y-4 text-sm">
              <p className="text-text">
                {t('stories.asA')} <b>{story.asA}</b>, {t('stories.iWant')} <b>{story.iWant}</b>, {t('stories.soThat')}{' '}
                <b>{story.soThat}</b>.
              </p>
              {story.status === 'discarded' && (
                <Notice tone="warning">
                  {t(story.outOfScope ? 'stories.discardedOos' : 'stories.discardedMsg', {
                    reason: story.discardReason,
                  })}
                </Notice>
              )}
              {story.status === 'merged' && (
                <Notice tone="info">{t('stories.mergedMsg', { id: story.mergedInto })}</Notice>
              )}

              <div>
                <div className="mb-1 text-xs font-medium text-muted">{t('stories.criteria')}</div>
                {story.criteria.length === 0 ? (
                  <Notice tone="warning">{t('stories.noCriteria')}</Notice>
                ) : (
                  <div className="space-y-2">
                    {story.criteria.map((c, i) => {
                      const issues = validateCriteria(story.criteria).filter((x) => x.scenario === i)
                      return (
                        <div key={i}>
                          <Code className={cn('whitespace-pre-wrap', issues.length > 0 && 'ring-1 ring-critical')}>
                            {c}
                          </Code>
                          {issues.length === 0 ? (
                            <div className="mt-1 flex items-center gap-1 text-xs text-good-ink">
                              <CheckCircle2 size={12} /> {t('gherkin.valid')}
                            </div>
                          ) : (
                            <GherkinIssues issues={issues} />
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <Links label={t('stories.rules')} items={story.rules} />
                <Links label={t('stories.screens')} items={story.screens} />
                <Links label={t('stories.contracts')} items={story.contracts} />
                <Links label={t('stories.nodes')} items={story.nodes} />
              </div>
              {!traced(story) && <Notice tone="warning">{t('stories.untracedHint')}</Notice>}

              <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                <Meta label={t('stories.originLabel')} value={t(`stories.origin.${story.origin}`)} />
                <Meta label={t('stories.priority')} value={story.priority} />
                <Meta label={t('stories.estimate')} value={t('stories.points', { count: story.points })} />
                <Meta label={t('stories.wave')} value={waveLabel(plan, story.id, t)} />
              </dl>
              <div className="text-xs text-muted">
                {t('stories.sourceLabel')}: <span className="font-mono">{story.source}</span>
              </div>

              <div>
                <div className="mb-1 text-xs font-medium text-muted">{t('stories.dependsOn')}</div>
                {story.dependsOn.length === 0 ? (
                  <span className="text-xs text-muted">{t('stories.noDependencies')}</span>
                ) : (
                  <ul className="space-y-1">
                    {story.dependsOn.map((d) => (
                      <li key={d.story} className="flex flex-wrap items-center gap-2 text-xs">
                        <button className="font-mono text-info hover:underline" onClick={() => setSelected(d.story)}>
                          {d.story}
                        </button>
                        <Badge tone={d.kind === 'hard' ? 'critical' : 'neutral'}>{t(`storyPlan.kind.${d.kind}`)}</Badge>
                        <span className="text-text-2">{d.reason}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                {active(story) ? (
                  <>
                    <Button size="sm" disabled={!editable} onClick={() => setEditing(story)}>
                      <Pencil size={14} /> {t('stories.edit')}
                    </Button>
                    <Button
                      size="sm"
                      disabled={!editable || story.criteria.length + story.rules.length < 2}
                      onClick={() => setSplitting(true)}
                    >
                      <Scissors size={14} /> {t('stories.split')}
                    </Button>
                    <Button size="sm" disabled={!editable} onClick={() => setMerging(true)}>
                      <GitMerge size={14} /> {t('stories.merge')}
                    </Button>
                    <Button size="sm" variant="ghost" disabled={!editable} onClick={() => setDiscarding(true)}>
                      <Trash2 size={14} /> {t('stories.discard')}
                    </Button>
                  </>
                ) : (
                  story.status === 'discarded' && (
                    <Button
                      size="sm"
                      disabled={!editable}
                      onClick={() => (restoreStory(story.id), toast(t('stories.restored')))}
                    >
                      <RotateCcw size={14} /> {t('stories.restore')}
                    </Button>
                  )
                )}
                {!editable && <span className="self-center text-xs text-muted">{t('stories.readOnly')}</span>}
              </div>
            </CardBody>
          </Card>

          {suggestions.length > 0 && active(story) && (
            <Card>
              <CardHeader title={t('stories.suggestions')} subtitle={t('stories.suggestionsHint')} />
              <CardBody className="space-y-3">
                {suggestions.map((g) => (
                  <div key={g.id} className="rounded-md border border-border p-3">
                    <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-text-2">
                      <Bot size={14} /> {t(`stories.suggestionKind.${g.kind}`)}
                    </div>
                    <Code className="whitespace-pre-wrap">{g.text}</Code>
                    <div className="mt-2 flex gap-2">
                      <Button
                        size="sm"
                        disabled={!editable}
                        onClick={() => {
                          if (g.kind === 'missingCriterion')
                            saveStory({ ...story, criteria: [...story.criteria, g.text] }, t('stories.historyAccepted'))
                          else setSplitting(true)
                          dismissSuggestion(g.id)
                        }}
                      >
                        {t('stories.accept')}
                      </Button>
                      <Button size="sm" variant="ghost" disabled={!editable} onClick={() => dismissSuggestion(g.id)}>
                        {t('stories.dismiss')}
                      </Button>
                    </div>
                  </div>
                ))}
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-1.5">
                  <History size={14} /> {t('stories.history')}
                </span>
              }
            />
            <ul className="divide-y divide-border">
              {history.filter((h) => h.story === story.id).length === 0 && (
                <li className="px-5 py-3 text-xs text-muted">{t('stories.noHistory')}</li>
              )}
              {history
                .filter((h) => h.story === story.id)
                .map((h, i) => (
                  <li key={i} className="flex flex-wrap gap-x-2 px-5 py-2 text-xs">
                    <span className="font-mono text-muted">v{h.version}</span>
                    <span className="text-muted tabular">{formatDateTime(h.at)}</span>
                    <span className="font-medium text-text">{h.by}</span>
                    <span className="text-text-2">{h.change}</span>
                  </li>
                ))}
            </ul>
          </Card>
        </div>
      </div>

      {editing && (
        <StoryForm
          key={editing.id}
          story={editing}
          stories={stories}
          onClose={() => setEditing(null)}
          onSaved={(id) => setSelected(id)}
        />
      )}
      {splitting && <SplitForm story={story} onClose={() => setSplitting(false)} onDone={(id) => setSelected(id)} />}
      {merging && (
        <MergeForm story={story} stories={live.filter((s) => s.id !== story.id)} onClose={() => setMerging(false)} />
      )}
      {discarding && <DiscardForm story={story} stories={live} onClose={() => setDiscarding(false)} />}
    </div>
  )
}

function waveLabel(plan: string[][], id: string, t: (k: string, o?: Record<string, unknown>) => string) {
  const w = plan.findIndex((x) => x.includes(id))
  return w === -1 ? t('storyPlan.notPlanned') : t('storyPlan.wave', { n: w + 1 })
}

function blankStory(id: string): UserStory {
  return {
    id,
    feature: storyFeatures[0].id,
    title: '',
    asA: '',
    iWant: '',
    soThat: '',
    criteria: [],
    rules: [],
    screens: [],
    contracts: [],
    nodes: [],
    origin: 'user',
    source: 'Created in the platform',
    status: 'draft',
    priority: 'P1',
    points: 3,
    dependsOn: [],
    version: 0,
  }
}

function Gap({ label, items, tone = 'warning' }: { label: string; items: string[]; tone?: 'warning' | 'neutral' }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <AlertTriangle size={14} className={tone === 'warning' ? 'text-warning' : 'text-muted'} />
      <span className="text-text-2">{label}</span>
      {items.map((i) => (
        <span key={i} className="font-mono text-xs text-text">
          {i}
        </span>
      ))}
    </div>
  )
}

function GherkinIssues({ issues, numbered }: { issues: GherkinIssue[]; numbered?: boolean }) {
  const { t } = useTranslation()
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-critical-ink">
      {issues.map((x, i) => (
        <li key={i} className="flex items-start gap-1">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>
            {numbered && <b>{t('gherkin.scenario', { n: x.scenario + 1 })} · </b>}
            {x.code === 'outOfOrder'
              ? t('gherkin.issue.outOfOrder', {
                  line: x.line,
                  detail: t(`gherkin.step.${x.detail}`),
                  after: t(`gherkin.step.${x.after}`),
                })
              : t(`gherkin.issue.${x.code}`, { line: x.line, detail: x.detail })}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Links({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted">{label}</div>
      {items.length === 0 ? (
        <span className="text-xs text-muted">—</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {items.map((i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text"
            >
              <Link2 size={10} className="text-muted" /> {i}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="text-text">{value}</dd>
    </div>
  )
}

function StoryForm({
  story,
  stories,
  onClose,
  onSaved,
}: {
  story: UserStory
  stories: UserStory[]
  onClose: () => void
  onSaved: (id: string) => void
}) {
  const { t } = useTranslation()
  const isNew = story.version === 0
  const [draft, setDraft] = useState<UserStory>(story)
  const [criteria, setCriteria] = useState(story.criteria.join('\n\n'))
  const others = useMemo(() => stories.filter((s) => s.id !== story.id && active(s)), [stories, story.id])
  const scenarios = splitScenarios(criteria)
  const gherkin = validateCriteria(scenarios)
  const valid = draft.title.trim() && draft.asA.trim() && draft.iWant.trim() && gherkin.length === 0
  const upd = (p: Partial<UserStory>) => setDraft({ ...draft, ...p })
  const hasDep = (id: string) => draft.dependsOn.find((d) => d.story === id)

  return (
    <Drawer
      open
      wide
      onClose={onClose}
      title={isNew ? t('stories.newTitle', { id: story.id }) : t('stories.editTitle', { id: story.id })}
      description={t('stories.formHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!valid}
            onClick={() => {
              const saved = { ...draft, criteria: scenarios }
              saveStory(
                isNew ? { ...saved, version: 0 } : saved,
                isNew ? t('stories.historyCreated') : t('stories.historyEdited'),
              )
              toast(t('stories.saved'))
              onSaved(story.id)
              onClose()
            }}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('stories.title')}>
          <Input value={draft.title} onChange={(e) => upd({ title: e.target.value })} />
        </Field>
        <Field label={t('stories.feature')}>
          <Select value={draft.feature} onChange={(e) => upd({ feature: e.target.value })}>
            {storyFeatures.map((f) => (
              <option key={f.id} value={f.id}>
                {f.id} · {f.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('stories.asA')}>
          <Input value={draft.asA} onChange={(e) => upd({ asA: e.target.value })} placeholder="back-office agent" />
        </Field>
        <Field label={t('stories.iWant')}>
          <Input value={draft.iWant} onChange={(e) => upd({ iWant: e.target.value })} />
        </Field>
        <Field label={t('stories.soThat')}>
          <Input value={draft.soThat} onChange={(e) => upd({ soThat: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('stories.priority')}>
            <Select value={draft.priority} onChange={(e) => upd({ priority: e.target.value as UserStory['priority'] })}>
              <option>P0</option>
              <option>P1</option>
              <option>P2</option>
            </Select>
          </Field>
          <Field label={t('stories.estimate')}>
            <Select value={draft.points} onChange={(e) => upd({ points: Number(e.target.value) })}>
              {[1, 2, 3, 5, 8, 13].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </div>
      <Field label={t('stories.criteria')} hint={t('stories.criteriaHint')}>
        <Textarea
          rows={7}
          value={criteria}
          onChange={(e) => setCriteria(e.target.value)}
          className={cn('font-mono text-xs', gherkin.length > 0 && 'border-critical')}
          placeholder={'Scenario: …\n  Given …\n  When …\n  Then …'}
          aria-invalid={gherkin.length > 0}
        />
        {scenarios.length > 0 &&
          (gherkin.length === 0 ? (
            <div className="mt-1 flex items-center gap-1 text-xs text-good-ink">
              <CheckCircle2 size={12} /> {t('gherkin.allValid', { count: scenarios.length })}
            </div>
          ) : (
            <GherkinIssues issues={gherkin} numbered />
          ))}
      </Field>
      <Field label={t('stories.rules')}>
        <CheckboxGroup
          options={rules.map((r) => ({
            id: r.id,
            label: (
              <span>
                <span className="font-mono text-xs">{r.id}</span> {r.name}
              </span>
            ),
          }))}
          value={draft.rules}
          onChange={(v) => upd({ rules: v })}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('stories.screens')}>
          <CheckboxGroup
            columns={1}
            options={screenSpecs.map((x) => ({ id: x.id, label: `${x.id} ${x.name}` }))}
            value={draft.screens}
            onChange={(v) => upd({ screens: v })}
          />
        </Field>
        <Field label={t('stories.contracts')}>
          <CheckboxGroup
            columns={1}
            options={contracts.map((c) => ({ id: c.id, label: `${c.id} ${c.method} ${c.path}` }))}
            value={draft.contracts}
            onChange={(v) => upd({ contracts: v })}
          />
        </Field>
      </div>
      <Field label={t('stories.dependsOn')} hint={t('stories.dependsOnHint')}>
        <ul className="space-y-1.5">
          {others.map((o) => {
            const d = hasDep(o.id)
            return (
              <li key={o.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!d}
                  onChange={() =>
                    upd({
                      dependsOn: d
                        ? draft.dependsOn.filter((x) => x.story !== o.id)
                        : [...draft.dependsOn, { story: o.id, kind: 'soft', reason: t('stories.depByUser') }],
                    })
                  }
                  className="accent-[var(--series-1)]"
                  aria-label={o.id}
                />
                <span className="font-mono text-xs text-info">{o.id}</span>
                <span className="flex-1 truncate text-text">{o.title}</span>
                {d && (
                  <div className="w-32">
                    <Select
                      className="h-8"
                      value={d.kind}
                      onChange={(e) =>
                        upd({
                          dependsOn: draft.dependsOn.map((x) =>
                            x.story === o.id ? { ...x, kind: e.target.value as 'hard' | 'soft' } : x,
                          ),
                        })
                      }
                      aria-label={t('stories.depKind')}
                    >
                      <option value="hard">{t('storyPlan.kind.hard')}</option>
                      <option value="soft">{t('storyPlan.kind.soft')}</option>
                    </Select>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </Field>
      {draft.rules.length + draft.screens.length + draft.contracts.length + draft.nodes.length === 0 && (
        <Notice tone="warning">{t('stories.untracedHint')}</Notice>
      )}
      <Notice tone="info">{t('stories.auditNote')}</Notice>
    </Drawer>
  )
}

function SplitForm({
  story,
  onClose,
  onDone,
}: {
  story: UserStory
  onClose: () => void
  onDone: (id: string) => void
}) {
  const { t } = useTranslation()
  const [title, setTitle] = useState(`${story.title} (2)`)
  const [criteria, setCriteria] = useState<string[]>([])
  const [ruleIds, setRuleIds] = useState<string[]>([])
  return (
    <Drawer
      open
      onClose={onClose}
      title={t('stories.splitTitle', { id: story.id })}
      description={t('stories.splitHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!title.trim() || criteria.length + ruleIds.length === 0}
            onClick={() => {
              const id = splitStory(story.id, title.trim(), criteria.map(Number), ruleIds)
              toast(t('stories.splitDone', { id }))
              onDone(id)
              onClose()
            }}
          >
            <Scissors size={14} /> {t('stories.split')}
          </Button>
        </>
      }
    >
      <Field label={t('stories.newStoryTitle')}>
        <Input value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      {story.criteria.length > 0 && (
        <Field label={t('stories.moveCriteria')}>
          <CheckboxGroup
            columns={1}
            options={story.criteria.map((c, i) => ({
              id: String(i),
              label: <span className="text-xs">{c.split('\n')[0]}</span>,
            }))}
            value={criteria}
            onChange={setCriteria}
          />
        </Field>
      )}
      {story.rules.length > 0 && (
        <Field label={t('stories.moveRules')}>
          <CheckboxGroup
            options={story.rules.map((r) => ({ id: r, label: r }))}
            value={ruleIds}
            onChange={setRuleIds}
          />
        </Field>
      )}
      <Notice tone="info">{t('stories.splitNote')}</Notice>
    </Drawer>
  )
}

function MergeForm({ story, stories, onClose }: { story: UserStory; stories: UserStory[]; onClose: () => void }) {
  const { t } = useTranslation()
  const [other, setOther] = useState(stories.find((s) => s.feature === story.feature)?.id ?? stories[0]?.id ?? '')
  return (
    <Drawer
      open
      onClose={onClose}
      title={t('stories.mergeTitle', { id: story.id })}
      description={t('stories.mergeHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!other}
            onClick={() => {
              mergeStories(story.id, other)
              toast(t('stories.mergeDone', { other, id: story.id }))
              onClose()
            }}
          >
            <GitMerge size={14} /> {t('stories.merge')}
          </Button>
        </>
      }
    >
      <Field label={t('stories.mergeWith')}>
        <Select value={other} onChange={(e) => setOther(e.target.value)}>
          {stories.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id} · {s.title}
            </option>
          ))}
        </Select>
      </Field>
      <Notice tone="info">{t('stories.mergeNote')}</Notice>
    </Drawer>
  )
}

function DiscardForm({ story, stories, onClose }: { story: UserStory; stories: UserStory[]; onClose: () => void }) {
  const { t } = useTranslation()
  const [reason, setReason] = useState('')
  const [outOfScope, setOutOfScope] = useState(false)
  const dependents = stories.filter((s) => s.dependsOn.some((d) => d.story === story.id))
  const orphanRules = story.rules.filter((r) => !stories.some((s) => s.id !== story.id && s.rules.includes(r)))
  return (
    <Drawer
      open
      onClose={onClose}
      title={t('stories.discardTitle', { id: story.id })}
      description={t('stories.discardHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="danger"
            disabled={reason.trim().length < 5}
            onClick={() => {
              discardStory(story.id, reason.trim(), outOfScope)
              toast(t('stories.discarded'))
              onClose()
            }}
          >
            <Trash2 size={14} /> {t('stories.discard')}
          </Button>
        </>
      }
    >
      <Field label={t('stories.reason')} hint={t('stories.reasonHint')}>
        <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <label className="flex items-center gap-2 text-sm text-text">
        <input
          type="checkbox"
          checked={outOfScope}
          onChange={(e) => setOutOfScope(e.target.checked)}
          className="accent-[var(--series-1)]"
        />
        {t('stories.markOutOfScope')}
      </label>
      {orphanRules.length > 0 && (
        <Notice tone="warning">{t('stories.discardRules', { rules: orphanRules.join(', ') })}</Notice>
      )}
      {dependents.length > 0 && (
        <Notice tone="warning">
          {t('stories.discardDependents', { stories: dependents.map((s) => s.id).join(', ') })}
        </Notice>
      )}
    </Drawer>
  )
}
