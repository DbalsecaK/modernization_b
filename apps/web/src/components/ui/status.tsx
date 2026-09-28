import { useTranslation } from 'react-i18next'
import { AlertTriangle, CheckCircle2, CircleDashed, Clock, Loader2, PauseCircle, XCircle } from 'lucide-react'
import type { PhaseStatus, SupportLevel, Verdict } from '@/mocks/types'
import { Badge } from './primitives'

// Status colors always travel with an icon and a label, never alone.
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const { t } = useTranslation()
  const map = {
    PROVEN: { tone: 'good', Icon: CheckCircle2 },
    PARTLY_PROVEN: { tone: 'warning', Icon: AlertTriangle },
    NOT_PROVEN: { tone: 'critical', Icon: XCircle },
    NOT_VERIFIED: { tone: 'neutral', Icon: CircleDashed },
  } as const
  const { tone, Icon } = map[verdict]
  return (
    <Badge tone={tone}>
      <Icon size={12} aria-hidden />
      {t(`verdict.${verdict}`)}
    </Badge>
  )
}

export function PhaseStatusIcon({ status, size = 16 }: { status: PhaseStatus; size?: number }) {
  const { t } = useTranslation()
  const label = t(`phaseStatus.${status}`)
  switch (status) {
    case 'done':
      return <CheckCircle2 size={size} className="text-good" aria-label={label} />
    case 'running':
      return <Loader2 size={size} className="animate-spin text-info" aria-label={label} />
    case 'waiting':
      return <PauseCircle size={size} className="text-warning" aria-label={label} />
    case 'failed':
      return <XCircle size={size} className="text-critical" aria-label={label} />
    default:
      return <Clock size={size} className="text-muted" aria-label={label} />
  }
}

export function LevelBadge({ level }: { level: SupportLevel }) {
  const { t } = useTranslation()
  const tone = level === 'certified' ? 'accent' : level === 'assisted' ? 'info' : 'neutral'
  return <Badge tone={tone}>{t(`level.${level}`)}</Badge>
}
