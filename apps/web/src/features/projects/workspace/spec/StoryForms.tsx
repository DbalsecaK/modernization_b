import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, GitMerge, Loader2, Scissors, Trash2 } from 'lucide-react'
import { cn } from '@/lib/cn'
import { splitScenarios } from '@/lib/gherkin'
import { ApiError } from '@/api/client'
import {
  GHERKIN_DEBOUNCE_MS,
  useCreateStory,
  useDiscardStory,
  useGherkin,
  useMergeStory,
  useSplitStory,
  useUpdateStory,
  type GherkinProblem,
  type StoryInput,
  type StoryOut,
} from '@/api/spec'
import { Button, Field, Input, Select } from '@/components/ui/primitives'
import { CheckboxGroup, Drawer, Textarea, toast } from '@/components/ui/overlay'
import { Notice } from '../../NewProjectWizard'
import { dependentsOf, gherkinProblemsOf, orphanLinks, type RuleView } from './model'
import { errorText, GherkinProblems } from './shared'

const ESTIMATES = [1, 2, 3, 5, 8, 13, 21]

/** Create (story = null) or edit a story. The criteria are validated live by the server while the person types. */
export function StoryForm({
  projectId,
  story,
  rules,
  features,
  onClose,
  onSaved,
}: {
  projectId: string
  story: StoryOut | null
  rules: RuleView[]
  features: string[]
  onClose: () => void
  onSaved: (key: string) => void
}) {
  const { t } = useTranslation()
  const featureList = useId()
  const create = useCreateStory(projectId)
  const update = useUpdateStory(projectId)
  const [draft, setDraft] = useState<StoryInput>({
    feature: story?.feature ?? '',
    title: story?.title ?? '',
    narrative: story?.narrative ?? '',
    criteria: story?.criteria ?? [],
    links: story?.links ?? [],
    priority: (story?.priority as StoryInput['priority']) ?? 'P1',
    estimate: story?.estimate ?? 3,
  })
  const [criteriaText, setCriteriaText] = useState((story?.criteria ?? []).join('\n\n'))
  const [rejected, setRejected] = useState<GherkinProblem[]>([])
  const scenarios = splitScenarios(criteriaText)
  const gherkin = useGherkin(scenarios, { debounce: GHERKIN_DEBOUNCE_MS })
  // Shown only when they belong to the text on screen (not to an older one still being answered).
  const problems = gherkin.current ? (gherkin.data?.problems ?? []) : []
  const knownInvalid = gherkin.current && gherkin.data?.valid === false
  const shownProblems = problems.length > 0 ? problems : rejected
  const valid = draft.title.trim().length >= 3 && !knownInvalid
  const pending = create.isPending || update.isPending
  const upd = (p: Partial<StoryInput>) => setDraft({ ...draft, ...p })
  const hasRuleLinks = (draft.links ?? []).length > 0

  const save = () => {
    const body: StoryInput = { ...draft, title: draft.title.trim(), criteria: scenarios }
    const options = {
      onSuccess: (saved: StoryOut) => {
        toast(t('stories.saved'))
        onSaved(saved.key)
        onClose()
      },
      onError: (e: unknown) => {
        if (e instanceof ApiError && e.code === 'invalid_gherkin') setRejected(gherkinProblemsOf(e.problems))
        toast(errorText(e, t('common.error')))
      },
    }
    if (story) update.mutate({ key: story.key, body }, options)
    else create.mutate(body, options)
  }

  return (
    <Drawer
      open
      wide
      onClose={onClose}
      title={story ? t('stories.editTitle', { id: story.key }) : t('stories.createTitle')}
      description={t('stories.formHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={!valid || pending} onClick={save}>
            {pending && <Loader2 size={14} className="animate-spin" />} {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('stories.title')} hint={t('stories.titleHint')}>
          <Input value={draft.title} onChange={(e) => upd({ title: e.target.value })} maxLength={200} />
        </Field>
        <Field label={t('stories.feature')}>
          <Input
            value={draft.feature}
            onChange={(e) => upd({ feature: e.target.value })}
            list={featureList}
            maxLength={200}
          />
          <datalist id={featureList}>
            {features.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
        </Field>
      </div>
      <Field label={t('stories.narrative')}>
        <Textarea
          rows={3}
          value={draft.narrative}
          onChange={(e) => upd({ narrative: e.target.value })}
          placeholder={t('stories.narrativePlaceholder')}
          maxLength={2000}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3 sm:w-1/2">
        <Field label={t('stories.priority')}>
          <Select value={draft.priority} onChange={(e) => upd({ priority: e.target.value as StoryInput['priority'] })}>
            <option>P0</option>
            <option>P1</option>
            <option>P2</option>
          </Select>
        </Field>
        <Field label={t('stories.estimate')}>
          <Select value={draft.estimate} onChange={(e) => upd({ estimate: Number(e.target.value) })}>
            {[...new Set([...ESTIMATES, draft.estimate])]
              .sort((a, b) => a - b)
              .map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
          </Select>
        </Field>
      </div>
      <div>
        <Field label={t('stories.criteria')} hint={t('stories.criteriaHint')}>
          <Textarea
            rows={8}
            value={criteriaText}
            onChange={(e) => {
              setCriteriaText(e.target.value)
              setRejected([])
            }}
            className={cn('font-mono text-xs', shownProblems.length > 0 && 'border-critical')}
            placeholder={'Scenario: …\n  Given …\n  When …\n  Then …'}
            aria-invalid={shownProblems.length > 0}
          />
        </Field>
        <div aria-live="polite">
          {scenarios.length > 0 && !gherkin.current && (
            <div className="mt-1 flex items-center gap-1 text-xs text-muted">
              <Loader2 size={12} className="animate-spin" /> {t('gherkin.checking')}
            </div>
          )}
          {gherkin.isError && <div className="mt-1 text-xs text-warning-ink">{t('gherkin.unavailable')}</div>}
          {scenarios.length > 0 && gherkin.current && gherkin.data?.valid && (
            <div className="mt-1 flex items-center gap-1 text-xs text-good-ink">
              <CheckCircle2 size={12} /> {t('gherkin.allValid', { count: scenarios.length })}
            </div>
          )}
          {shownProblems.length > 0 && <GherkinProblems problems={shownProblems} numbered />}
        </div>
      </div>
      <Field label={t('stories.rules')}>
        {rules.length === 0 ? (
          <span className="text-xs text-muted">—</span>
        ) : (
          <CheckboxGroup
            options={rules.map((r) => ({
              id: r.key,
              label: (
                <span>
                  <span className="font-mono text-xs">{r.key}</span> {r.name}
                </span>
              ),
            }))}
            value={draft.links ?? []}
            onChange={(v) => upd({ links: v })}
          />
        )}
      </Field>
      {!hasRuleLinks && <Notice tone="warning">{t('stories.untracedHint')}</Notice>}
      <Notice tone="info">{t('stories.auditNote')}</Notice>
    </Drawer>
  )
}

export function SplitForm({
  projectId,
  story,
  onClose,
  onDone,
}: {
  projectId: string
  story: StoryOut
  onClose: () => void
  onDone: (key: string) => void
}) {
  const { t } = useTranslation()
  const split = useSplitStory(projectId)
  const [title, setTitle] = useState(`${story.title} (2)`)
  const [criteria, setCriteria] = useState<string[]>([])
  const [links, setLinks] = useState<string[]>([])
  return (
    <Drawer
      open
      onClose={onClose}
      title={t('stories.splitTitle', { id: story.key })}
      description={t('stories.splitHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={title.trim().length < 3 || criteria.length + links.length === 0 || split.isPending}
            onClick={() =>
              split.mutate(
                { key: story.key, body: { title: title.trim(), criteria: criteria.map(Number), links } },
                {
                  onSuccess: (result) => {
                    const created = result.find((s) => s.key !== story.key)?.key ?? story.key
                    toast(t('stories.splitDone', { id: created }))
                    onDone(created)
                    onClose()
                  },
                  onError: (e) => toast(errorText(e, t('common.error'))),
                },
              )
            }
          >
            <Scissors size={14} /> {t('stories.split')}
          </Button>
        </>
      }
    >
      <Field label={t('stories.newStoryTitle')}>
        <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
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
      {story.links.length > 0 && (
        <Field label={t('stories.moveRules')}>
          <CheckboxGroup options={story.links.map((r) => ({ id: r, label: r }))} value={links} onChange={setLinks} />
        </Field>
      )}
      <Notice tone="info">{t('stories.splitNote')}</Notice>
    </Drawer>
  )
}

/** The chosen story is absorbed by `story` (the API merges `other` into `story`). */
export function MergeForm({
  projectId,
  story,
  stories,
  onClose,
}: {
  projectId: string
  story: StoryOut
  stories: StoryOut[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const merge = useMergeStory(projectId)
  const [other, setOther] = useState(stories.find((s) => s.feature === story.feature)?.key ?? stories[0]?.key ?? '')
  return (
    <Drawer
      open
      onClose={onClose}
      title={t('stories.mergeTitle', { id: story.key })}
      description={t('stories.mergeHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!other || merge.isPending}
            onClick={() =>
              merge.mutate(
                { key: other, into: story.key },
                {
                  onSuccess: () => {
                    toast(t('stories.mergeDone', { other, id: story.key }))
                    onClose()
                  },
                  onError: (e) => toast(errorText(e, t('common.error'))),
                },
              )
            }
          >
            <GitMerge size={14} /> {t('stories.merge')}
          </Button>
        </>
      }
    >
      {stories.length === 0 ? (
        <Notice tone="info">{t('stories.nothingToMerge')}</Notice>
      ) : (
        <Field label={t('stories.mergeWith')}>
          <Select value={other} onChange={(e) => setOther(e.target.value)}>
            {stories.map((s) => (
              <option key={s.key} value={s.key}>
                {s.key} · {s.title}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Notice tone="info">{t('stories.mergeNote')}</Notice>
    </Drawer>
  )
}

export function DiscardForm({
  projectId,
  story,
  stories,
  onClose,
}: {
  projectId: string
  story: StoryOut
  stories: StoryOut[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const discard = useDiscardStory(projectId)
  const [reason, setReason] = useState('')
  const [outOfScope, setOutOfScope] = useState(false)
  const dependents = dependentsOf(story.key, stories)
  const orphans = orphanLinks(story, stories)
  return (
    <Drawer
      open
      onClose={onClose}
      title={t('stories.discardTitle', { id: story.key })}
      description={t('stories.discardHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="danger"
            disabled={reason.trim().length < 5 || discard.isPending}
            onClick={() =>
              discard.mutate(
                { key: story.key, body: { reason: reason.trim(), outOfScope } },
                {
                  onSuccess: () => {
                    toast(t('stories.discarded'))
                    onClose()
                  },
                  onError: (e) => toast(errorText(e, t('common.error'))),
                },
              )
            }
          >
            <Trash2 size={14} /> {t('stories.discard')}
          </Button>
        </>
      }
    >
      <Field label={t('stories.reason')} hint={t('stories.reasonHint')}>
        <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
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
      {orphans.length > 0 && !outOfScope && (
        <Notice tone="warning">{t('stories.discardRules', { rules: orphans.join(', ') })}</Notice>
      )}
      {dependents.length > 0 && (
        <Notice tone="warning">{t('stories.discardDependents', { stories: dependents.join(', ') })}</Notice>
      )}
    </Drawer>
  )
}
