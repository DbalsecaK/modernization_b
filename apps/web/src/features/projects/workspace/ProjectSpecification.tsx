import { useMemo, useState } from 'react'
import { useSearch } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Loader2, ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/cn'
import { ApiError } from '@/api/client'
import type { ProjectDetail } from '@/api/projects'
import { useContracts } from '@/api/architecture'
import { useQuestions } from '@/api/runs'
import { useScreens } from '@/api/screens'
import { useC1Check, useCoverage, usePlan, useRules, useStories, type C1Check } from '@/api/spec'
import { Button, Card, CardBody, EmptyState } from '@/components/ui/primitives'
import { QuestionList } from '@/features/decisions/QuestionCard'
import { isActive, toRuleView } from './spec/model'
import { ContractsView } from './spec/ContractsView'
import { PlanView } from './spec/PlanView'
import { RulesView } from './spec/RulesView'
import { ScreensView } from './spec/ScreensView'
import { StoriesView } from './spec/StoriesView'

const VIEWS = ['rules', 'stories', 'plan', 'screens', 'contracts', 'questions'] as const
type View = (typeof VIEWS)[number]

// Specification tab (spec 7.7, 4.1, 18.3), connected to the API: the rules the agents extracted, the user stories
// people review, the plan by waves, the screens (when the legacy has them; a Sybase stored-procedure estate has none),
// the HTTP contracts of the target and the questions of the human in the loop.
export function ProjectSpecification({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const search = useSearch({ strict: false }) as { view?: string }
  const [view, setView] = useState<View>(VIEWS.find((v) => v === search.view) ?? 'rules')
  const [story, setStory] = useState<string | null>(null)
  const rules = useRules(project.id)
  const stories = useStories(project.id)
  const coverage = useCoverage(project.id)
  const c1 = useC1Check(project.id)
  const plan = usePlan(project.id)
  const questions = useQuestions(project.id)
  const screens = useScreens(project.id)
  const contracts = useContracts(project.id)
  const ruleViews = useMemo(() => (rules.data ?? []).map(toRuleView), [rules.data])
  const perms = project.permissions
  const noPlan = plan.error instanceof ApiError && plan.error.status === 404

  if (rules.isLoading || stories.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('spec.loading')}
      </p>
    )
  }
  if (rules.isError || stories.isError) {
    const error = rules.error ?? stories.error
    return (
      <EmptyState
        title={t('spec.loadError')}
        description={error instanceof ApiError ? error.message : undefined}
        action={
          <Button
            size="sm"
            onClick={() => {
              void rules.refetch()
              void stories.refetch()
            }}
          >
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  if (ruleViews.length === 0 && (stories.data ?? []).length === 0) {
    return (
      <EmptyState
        title={t('spec.emptyTitle')}
        description={t('spec.emptyHint')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }

  const storyList = stories.data ?? []
  const openQuestions = (questions.data ?? []).filter((q) => q.status === 'open').length
  const counts: Record<View, number> = {
    rules: ruleViews.length,
    stories: storyList.filter(isActive).length,
    plan: plan.data?.waves.length ?? 0,
    screens: screens.data?.length ?? 0,
    contracts: contracts.data?.operations.length ?? 0,
    questions: openQuestions,
  }
  const openStory = (key: string) => {
    setStory(key)
    setView('stories')
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-surface p-1" role="tablist">
        {VIEWS.map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={cn(
              'rounded-md px-3 py-1.5 text-sm',
              view === v ? 'bg-brand text-brand-contrast' : 'text-text-2 hover:bg-surface-2',
            )}
          >
            {t(`spec.views.${v}`)} <span className="ml-1 text-xs opacity-80">{counts[v]}</span>
          </button>
        ))}
      </div>

      {(view === 'rules' || view === 'stories') && c1.data && <C1Readiness check={c1.data} onOpenRuns={onOpenRuns} />}

      {view === 'rules' && (
        <RulesView
          projectId={project.id}
          rules={ruleViews}
          coverage={coverage.data}
          questions={questions.data ?? []}
          onOpenStory={openStory}
        />
      )}
      {view === 'stories' && (
        <StoriesView
          projectId={project.id}
          stories={storyList}
          rules={ruleViews.filter((r) => r.status !== 'obsolete')}
          coverage={coverage.data}
          waves={plan.data?.waves ?? []}
          canEdit={perms.includes('story.edit')}
          canEditPlan={perms.includes('plan.edit')}
          selected={story}
          onSelect={setStory}
        />
      )}
      {view === 'plan' &&
        (plan.data ? (
          <PlanView projectId={project.id} plan={plan.data} stories={storyList} canEdit={perms.includes('plan.edit')} />
        ) : plan.isLoading ? (
          <p className="py-6 text-sm text-muted">{t('common.loading')}</p>
        ) : (
          <EmptyState
            title={noPlan ? t('storyPlan.noPlan') : t('spec.loadError')}
            description={noPlan ? t('storyPlan.noPlanHint') : undefined}
          />
        ))}
      {view === 'screens' && <ScreensView projectId={project.id} screens={screens.data ?? []} />}
      {view === 'contracts' && <ContractsView projectId={project.id} contracts={contracts.data ?? null} />}
      {view === 'questions' && (
        <QuestionList questions={questions.data ?? []} canAnswer={() => perms.includes('question.answer')} />
      )}
    </div>
  )
}

/** Why gate C1 (stories and plan) cannot be approved yet, as computed by the server. */
function C1Readiness({ check, onOpenRuns }: { check: C1Check; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  return (
    <Card className={check.canApprove ? 'border-good' : 'border-warning'}>
      <CardBody className="flex flex-wrap items-start gap-3 text-sm">
        {check.canApprove ? (
          <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" />
        ) : (
          <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" />
        )}
        <div className="min-w-0 flex-1">
          <p className="font-medium text-text">{check.canApprove ? t('spec.c1.ready') : t('spec.c1.blocked')}</p>
          {!check.canApprove && (
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-text-2">
              {check.blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
          {(check.warnings ?? []).length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-warning-ink">{t('spec.c1.coverageWarning')}</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-text-2">
                {(check.warnings ?? []).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        {check.canApprove && (
          <Button size="sm" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        )}
      </CardBody>
    </Card>
  )
}
