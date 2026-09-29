import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, FileText, Sparkles, UserRound } from 'lucide-react'
import { cn } from '@/lib/cn'
import { ApiError } from '@/api/client'
import { useAcceptRecommended, useAnswerQuestion, type Question } from '@/api/runs'
import { Badge, Button, Card, CardBody, Field, Select } from '@/components/ui/primitives'
import { Textarea, toast } from '@/components/ui/overlay'

const OTHER = '__other'

type Option = { key: string; label: string; rationale?: string }

function options(question: Question): Option[] {
  return [question.recommended as Option, ...(question.alternatives as Option[])]
}

// Decision card of the platform (spec 10.4): the recommended answer is preselected, the alternatives are in the same
// list and the person can always write their own answer. The answer resumes the run that asked.
export function QuestionCard({ question, canAnswer }: { question: Question; canAnswer: boolean }) {
  const { t } = useTranslation()
  const recommended = question.recommended as Option & { confidence?: number }
  const [choice, setChoice] = useState<string>(recommended.key)
  const [custom, setCustom] = useState('')
  const [comment, setComment] = useState('')
  const answer = useAnswerQuestion()
  const all = options(question)
  const option = all.find((o) => o.key === choice)
  const open = question.status === 'open'
  const canSubmit = choice === OTHER ? custom.trim().length > 1 : !!option

  const submit = () =>
    answer.mutate(
      {
        projectId: question.projectId,
        questionId: question.id,
        body:
          choice === OTHER
            ? { text: custom.trim(), comment: comment || null }
            : { option: choice, comment: comment || null },
      },
      {
        onSuccess: () => toast(t('questions.recorded')),
        onError: (e) => toast(e instanceof ApiError ? e.message : t('common.error')),
      },
    )

  return (
    <Card className={cn(!open && 'opacity-80')}>
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={question.impact === 'high' ? 'critical' : 'neutral'}>
            {t(`decisions.risk.${question.impact}`)}
          </Badge>
          <Badge tone="info">{t(`questions.reason.${question.reason}`)}</Badge>
          <Badge>{t(`phases.${question.phase}`, { defaultValue: question.phase })}</Badge>
          <span className="ml-auto flex items-center gap-1 text-xs text-muted">
            <UserRound size={12} /> {question.agentKey}
          </span>
        </div>
        <div>
          <h3 className="text-base font-semibold text-text">{question.questionText}</h3>
          {question.context && <p className="mt-1 text-sm whitespace-pre-line text-text-2">{question.context}</p>}
        </div>
        {question.evidence.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {question.evidence.map((e, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 font-mono text-xs text-text-2"
              >
                <FileText size={12} /> {String((e as { reference?: string }).reference ?? '')}
              </span>
            ))}
          </div>
        )}

        {!open ? (
          <div className="flex items-start gap-2 rounded-md bg-good/10 p-3 text-sm">
            <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" />
            <span className="text-text">
              <strong>
                {all.find((o) => o.key === question.answer)?.label ?? question.answer ?? t('questions.cancelled')}
              </strong>
              {question.answeredByName && (
                <span className="block text-xs text-muted">
                  {t('decisions.answeredBy', { name: question.answeredByName })}
                </span>
              )}
            </span>
          </div>
        ) : (
          <>
            <Field label={t('decisions.yourAnswer')}>
              <Select value={choice} onChange={(e) => setChoice(e.target.value)} disabled={!canAnswer}>
                {all.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.key === recommended.key ? `★ ${t('decisions.recommendedPrefix')}: ` : ''}
                    {o.label}
                  </option>
                ))}
                <option value={OTHER}>{t('decisions.otherAnswer')}</option>
              </Select>
            </Field>
            {option?.rationale && (
              <div
                className={cn(
                  'rounded-md p-3 text-sm',
                  option.key === recommended.key ? 'bg-accent/10' : 'bg-surface-2',
                )}
              >
                <div className="flex items-center gap-1.5 text-xs font-medium text-text">
                  {option.key === recommended.key && <Sparkles size={12} className="text-accent-ink" />}
                  {option.key === recommended.key ? t('decisions.whyRecommended') : t('decisions.whyOption')}
                  {option.key === recommended.key && recommended.confidence !== undefined && (
                    <Badge className="ml-auto">
                      {t('questions.confidence', { value: Math.round(recommended.confidence * 100) })}
                    </Badge>
                  )}
                </div>
                <p className="mt-1 text-text-2">{option.rationale}</p>
              </div>
            )}
            {choice === OTHER && (
              <Field label={t('decisions.customLabel')} hint={t('decisions.customHint')}>
                <Textarea value={custom} onChange={(e) => setCustom(e.target.value)} autoFocus />
              </Field>
            )}
            <Field label={t('decisions.comment')}>
              <Textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={2}
                placeholder={t('decisions.commentPlaceholder')}
              />
            </Field>
            <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
              {question.affects.length > 0 && (
                <span className="text-xs text-muted">
                  {t('decisions.impact', { items: question.affects.join(', ') })}
                </span>
              )}
              <Button
                variant="primary"
                className="ml-auto"
                disabled={!canAnswer || !canSubmit || answer.isPending}
                onClick={submit}
              >
                {t('decisions.submit')}
              </Button>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  )
}

/** Open and answered questions, with "accept every low-impact recommendation" per project. */
export function QuestionList({ questions, canAnswer }: { questions: Question[]; canAnswer: (q: Question) => boolean }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState<'open' | 'answered' | 'all'>('open')
  const accept = useAcceptRecommended()
  const open = questions.filter((q) => q.status === 'open')
  const lowImpact = open.filter((q) => q.impact === 'low' && canAnswer(q))
  const shown = questions.filter(
    (q) => filter === 'all' || (filter === 'open' ? q.status === 'open' : q.status !== 'open'),
  )

  const acceptAll = async () => {
    const byProject = new Map<string, string[]>()
    lowImpact.forEach((q) => byProject.set(q.projectId, [...(byProject.get(q.projectId) ?? []), q.id]))
    let count = 0
    for (const [projectId, questionIds] of byProject) {
      count += (await accept.mutateAsync({ projectId, questionIds })).answered
    }
    toast(t('decisions.bulkAccepted', { count }))
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {(['open', 'answered', 'all'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            aria-pressed={filter === f}
            className={cn(
              'rounded-full border px-3 py-1 text-sm',
              filter === f
                ? 'border-series-1 bg-series-1/10 text-text'
                : 'border-border text-text-2 hover:bg-surface-2',
            )}
          >
            {t(`decisions.filters.${f}`)} {f === 'open' && `(${open.length})`}
          </button>
        ))}
        <Button
          size="sm"
          className="ml-auto"
          disabled={lowImpact.length === 0 || accept.isPending}
          onClick={() => void acceptAll()}
        >
          <Sparkles size={14} /> {t('decisions.acceptLowRisk', { count: lowImpact.length })}
        </Button>
      </div>
      <p className="text-xs text-muted">{t('decisions.bulkHint')}</p>
      {shown.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted">
          {t('decisions.empty')}
        </p>
      ) : (
        shown.map((q) => <QuestionCard key={q.id} question={q} canAnswer={canAnswer(q)} />)
      )}
    </div>
  )
}
