import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { ArrowRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDate } from '@/lib/format'
import { projects, tasks } from '@/mocks/data'
import type { Task } from '@/mocks/types'
import { Badge, Card, PageHeader, Tabs } from '@/components/ui/primitives'
import { useTab } from '@/lib/useTab'
import { DecisionList } from '@/features/decisions/DecisionCard'
import { updateDecisions, useDecisions } from '@/features/decisions/store'

const tabFor: Record<Task['kind'], string> = {
  approveSpec: 'specification',
  reviewStories: 'specification',
  reviewPrototype: 'uiDesign',
  answerQuestion: 'specification',
  escalation: 'runs',
  signOff: 'validation',
  approveArchitecture: 'architecture',
}

const TABS = ['questions', 'approvals'] as const

export function TasksPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useTab(TABS, 'questions')
  const decisions = useDecisions()
  const [filter, setFilter] = useState<'all' | Task['kind']>('all')
  const approvals = tasks.filter((k) => k.kind !== 'answerQuestion' && k.kind !== 'escalation')
  const kinds = Array.from(new Set(approvals.map((k) => k.kind)))
  const list = approvals.filter((k) => filter === 'all' || k.kind === filter)
  const openCount = decisions.filter((d) => d.status === 'open').length

  return (
    <>
      <PageHeader title={t('tasks.title')} description={t('tasks.description')} />
      <Tabs
        tabs={[
          { id: 'questions', label: t('tasks.tabs.questions'), count: openCount },
          { id: 'approvals', label: t('tasks.tabs.approvals'), count: approvals.length },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'questions' && <DecisionList decisions={decisions} onChange={updateDecisions} />}
      {tab === 'approvals' && (
      <>
      <div className="mb-4 flex flex-wrap gap-2">
        {(['all', ...kinds] as const).map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            aria-pressed={filter === k}
            className={cn('rounded-full border px-3 py-1 text-sm', filter === k ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-text-2 hover:bg-surface-2')}
          >
            {k === 'all' ? t('tasks.all') : t(`tasks.kinds.${k}`)}
          </button>
        ))}
      </div>
      <Card>
        <ul className="divide-y divide-border">
          {list.map((task) => {
            const project = projects.find((p) => p.id === task.projectId)!
            return (
              <li key={task.id}>
                <Link
                  to="/projects/$projectId"
                  params={{ projectId: project.id }}
                  search={{ tab: tabFor[task.kind], view: task.kind === 'reviewStories' ? 'stories' : undefined }}
                  className="flex flex-wrap items-center gap-3 px-5 py-4 hover:bg-surface-2"
                >
                  <Badge tone={task.priority === 'high' ? 'critical' : 'neutral'}>{t(`tasks.kinds.${task.kind}`)}</Badge>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-text">{task.title}</div>
                    <div className="text-xs text-muted">{project.name}</div>
                  </div>
                  <span className="text-xs text-muted">{t('tasks.due', { date: formatDate(task.due) })}</span>
                  <ArrowRight size={16} className="text-muted" />
                </Link>
              </li>
            )
          })}
        </ul>
      </Card>
      </>
      )}
    </>
  )
}
