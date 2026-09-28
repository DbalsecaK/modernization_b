import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, FileCode2, FileText, FlaskConical, GitBranch, Sparkles, UserRound } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { Decision } from '@/mocks/data'
import { Badge, Button, Card, CardBody, Field, Select } from '@/components/ui/primitives'
import { Textarea, toast } from '@/components/ui/overlay'

const OTHER = '__other'
const evidenceIcon = { code: FileCode2, rule: GitBranch, test: FlaskConical, doc: FileText }

// Human-in-the-loop question (spec 10.4): the platform's recommendation is pre-selected, alternatives are
// in the same combobox, and the person can always write their own answer.
export function DecisionCard({ decision, onAnswer }: { decision: Decision; onAnswer: (answer: string) => void }) {
  const { t } = useTranslation()
  const [choice, setChoice] = useState(decision.recommended)
  const [custom, setCustom] = useState('')
  const [comment, setComment] = useState('')
  const [showComment, setShowComment] = useState(false)
  const option = decision.options.find((o) => o.id === choice)
  const answered = decision.status === 'answered'
  const canSubmit = choice === OTHER ? custom.trim().length > 3 : !!option

  return (
    <Card className={cn(answered && 'opacity-80')}>
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted">{decision.id}</span>
          <Badge tone={decision.risk === 'high' ? 'critical' : 'neutral'}>{t(`decisions.risk.${decision.risk}`)}</Badge>
          <Badge tone="info">{t(`decisions.reason.${decision.reason}`)}</Badge>
          <span className="ml-auto flex items-center gap-1 text-xs text-muted">
            <UserRound size={12} /> {decision.owner}
          </span>
        </div>
        <div>
          <h3 className="text-base font-semibold text-text">{decision.question}</h3>
          <p className="mt-1 text-sm text-text-2">{decision.context}</p>
          <p className="mt-1 text-xs text-muted">{t('decisions.raisedBy', { agent: decision.raisedBy })}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          {decision.evidence.map((e) => {
            const Icon = evidenceIcon[e.ref as keyof typeof evidenceIcon] ?? FileText
            return (
              <span
                key={e.label}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 font-mono text-xs text-text-2"
              >
                <Icon size={12} /> {e.label}
              </span>
            )
          })}
        </div>

        {answered ? (
          <div className="flex items-start gap-2 rounded-md bg-good/10 p-3 text-sm">
            <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" />
            <span className="text-text">
              <strong>{decision.answer}</strong>
              <span className="block text-xs text-muted">
                {t('decisions.answeredBy', { name: decision.answeredBy })}
              </span>
            </span>
          </div>
        ) : (
          <>
            <Field label={t('decisions.yourAnswer')}>
              <Select value={choice} onChange={(e) => setChoice(e.target.value)}>
                {decision.options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.id === decision.recommended ? `★ ${t('decisions.recommendedPrefix')}: ` : ''}
                    {o.label}
                  </option>
                ))}
                <option value={OTHER}>{t('decisions.otherAnswer')}</option>
              </Select>
            </Field>

            {option && (
              <div
                className={cn(
                  'rounded-md p-3 text-sm',
                  option.id === decision.recommended ? 'bg-accent/10' : 'bg-surface-2',
                )}
              >
                <div className="flex items-center gap-1.5 text-xs font-medium text-text">
                  {option.id === decision.recommended && <Sparkles size={12} className="text-accent-ink" />}
                  {option.id === decision.recommended ? t('decisions.whyRecommended') : t('decisions.whyOption')}
                  <Badge className="ml-auto">
                    {t('decisions.confidence', { level: t(`confidence.${option.confidence}`) })}
                  </Badge>
                </div>
                <p className="mt-1 text-text-2">{option.rationale}</p>
              </div>
            )}

            {choice === OTHER && (
              <Field label={t('decisions.customLabel')} hint={t('decisions.customHint')}>
                <Textarea value={custom} onChange={(e) => setCustom(e.target.value)} autoFocus />
              </Field>
            )}

            {showComment ? (
              <Field label={t('decisions.comment')}>
                <Textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={2}
                  placeholder={t('decisions.commentPlaceholder')}
                  autoFocus
                />
              </Field>
            ) : (
              <button className="text-xs font-medium text-info hover:underline" onClick={() => setShowComment(true)}>
                {t('decisions.addComment')}
              </button>
            )}

            <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
              <span className="text-xs text-muted">
                {t('decisions.impact', { items: decision.affects.join(', ') })}
              </span>
              <Button
                variant="primary"
                className="ml-auto"
                disabled={!canSubmit}
                onClick={() => {
                  const answer = choice === OTHER ? custom.trim() : option!.label
                  onAnswer(answer)
                  toast(t('decisions.recorded', { items: decision.affects.join(', ') }))
                }}
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

// List with filters and "accept all recommendations" for low-risk questions.
export function DecisionList({ decisions, onChange }: { decisions: Decision[]; onChange: (d: Decision[]) => void }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState<'open' | 'answered' | 'all'>('open')
  const open = decisions.filter((d) => d.status === 'open')
  const lowRisk = open.filter((d) => d.risk === 'low')
  const shown = decisions.filter((d) => filter === 'all' || d.status === filter)

  const answer = (id: string, text: string) =>
    onChange(
      decisions.map((d) => (d.id === id ? { ...d, status: 'answered', answer: text, answeredBy: 'David Balseca' } : d)),
    )

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
          disabled={lowRisk.length === 0}
          onClick={() => {
            onChange(
              decisions.map((d) =>
                d.status === 'open' && d.risk === 'low'
                  ? {
                      ...d,
                      status: 'answered',
                      answer: d.options.find((o) => o.id === d.recommended)!.label,
                      answeredBy: 'David Balseca',
                    }
                  : d,
              ),
            )
            toast(t('decisions.bulkAccepted', { count: lowRisk.length }))
          }}
        >
          <Sparkles size={14} /> {t('decisions.acceptLowRisk', { count: lowRisk.length })}
        </Button>
      </div>
      <p className="text-xs text-muted">{t('decisions.bulkHint')}</p>
      {shown.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted">
          {t('decisions.empty')}
        </p>
      ) : (
        shown.map((d) => <DecisionCard key={d.id} decision={d} onAnswer={(a) => answer(d.id, a)} />)
      )}
    </div>
  )
}
