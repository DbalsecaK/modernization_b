import { Link } from '@tanstack/react-router'
import { useQueries } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ArrowRight } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import { api, toApiError } from '@/api/client'
import { useTasks, type Question } from '@/api/runs'
import { Badge, Card, EmptyState, PageHeader, Tabs } from '@/components/ui/primitives'
import { useTab } from '@/lib/useTab'
import { QuestionList } from '@/features/decisions/QuestionCard'

const TABS = ['questions', 'approvals'] as const

// My tasks (spec 10.4, 18.2): the questions and the gate approvals the user can resolve, across every project they
// may see. The API filters them with OpenFGA; gates of runs the user launched are not listed (segregation of duties).
export function TasksPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useTab(TABS, 'questions')
  const tasks = useTasks()
  const all = tasks.data ?? []
  const questionTasks = all.filter((task) => task.kind === 'question')
  const approvals = all.filter((task) => task.kind === 'gate')
  const projectIds = Array.from(new Set(questionTasks.map((task) => task.projectId)))
  const wanted = new Set(questionTasks.map((task) => task.questionId))
  const questions = useQueries({
    queries: projectIds.map((projectId) => ({
      queryKey: ['projects', projectId, 'questions'],
      queryFn: async () => {
        const { data, error, response } = await api.GET('/api/v1/projects/{project_id}/questions', {
          params: { path: { project_id: projectId } },
        })
        if (!response.ok) throw toApiError(response, error)
        return data as Question[]
      },
    })),
  })
  const cards = questions.flatMap((q) => q.data ?? []).filter((q) => wanted.has(q.id))

  return (
    <>
      <PageHeader title={t('tasks.title')} description={t('tasks.description')} />
      <Tabs
        tabs={[
          { id: 'questions', label: t('tasks.tabs.questions'), count: questionTasks.length },
          { id: 'approvals', label: t('tasks.tabs.approvals'), count: approvals.length },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'questions' &&
        (questionTasks.length === 0 ? (
          <EmptyState title={t('tasks.noQuestions')} description={t('tasks.noQuestionsHint')} />
        ) : (
          // Only questions the user can answer reach this list (the API filters by question.answer).
          <QuestionList questions={cards} canAnswer={() => true} />
        ))}
      {tab === 'approvals' &&
        (approvals.length === 0 ? (
          <EmptyState title={t('tasks.noApprovals')} description={t('tasks.noApprovalsHint')} />
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {approvals.map((task) => (
                <li key={`${task.runId}-${task.gate}`}>
                  <Link
                    to="/projects/$projectId"
                    params={{ projectId: task.projectId }}
                    search={{ tab: 'runs' }}
                    className="flex flex-wrap items-center gap-3 px-5 py-4 hover:bg-surface-2"
                  >
                    <Badge tone="critical">{t('tasks.gate', { gate: task.gate })}</Badge>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-text">{t(`runsPage.gate.hint.${task.gate}`)}</div>
                      <div className="text-xs text-muted">{task.projectName}</div>
                    </div>
                    <span className="text-xs text-muted">
                      {t('tasks.since', { date: formatDateTime(task.createdAt) })}
                    </span>
                    <ArrowRight size={16} className="text-muted" />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        ))}
    </>
  )
}
