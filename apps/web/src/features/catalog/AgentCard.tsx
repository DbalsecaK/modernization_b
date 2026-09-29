import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Lock, Sparkles } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { CatalogAgent } from '@/api/projects'
import { Badge } from '@/components/ui/primitives'
import { LevelBadge } from '@/components/ui/status'

type Named = { name: string; nameEs?: string | null }
type Described = { description: string; descriptionEs?: string | null }

export function agentName(agent: Named, lang: string) {
  return lang === 'es' && agent.nameEs ? agent.nameEs : agent.name
}

export function agentDescription(agent: Described, lang: string) {
  return lang === 'es' && agent.descriptionEs ? agent.descriptionEs : agent.description
}

export function AgentCard({
  agent,
  selected,
  recommendedReason,
  modelWarning,
  onToggle,
}: {
  agent: CatalogAgent
  selected?: boolean
  recommendedReason?: string
  modelWarning?: string
  onToggle?: () => void
}) {
  const { t, i18n } = useTranslation()
  const interactive = !!onToggle
  const locked = agent.mandatory && interactive
  const name = agentName(agent, i18n.language)

  return (
    <div
      className={cn(
        'relative flex h-full flex-col rounded-lg border bg-surface p-4 transition-colors',
        selected ? 'border-series-1 ring-1 ring-series-1' : 'border-border',
        interactive && !locked && 'cursor-pointer hover:border-series-1/60',
      )}
      onClick={locked ? undefined : onToggle}
      role={interactive ? 'checkbox' : undefined}
      aria-checked={interactive ? !!selected : undefined}
      aria-disabled={locked || undefined}
      aria-label={interactive ? name : undefined}
      tabIndex={interactive && !locked ? 0 : undefined}
      onKeyDown={(e) => {
        if (!locked && onToggle && (e.key === ' ' || e.key === 'Enter')) {
          e.preventDefault()
          onToggle()
        }
      }}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-brand/10 text-sm font-semibold text-brand dark:bg-accent/15 dark:text-accent">
            {agent.name
              .split(' ')
              .map((w) => w[0])
              .slice(0, 2)
              .join('')
              .toUpperCase()}
          </span>
          <div>
            <div className="text-sm font-semibold text-text">{name}</div>
            <div className="text-xs text-muted">
              {t(`agentGroups.${agent.group}`)} · v{agent.version}
            </div>
          </div>
        </div>
        {interactive && (
          <span
            className={cn(
              'flex h-5 w-5 shrink-0 items-center justify-center rounded border',
              selected ? 'border-series-1 bg-series-1 text-white' : 'border-border',
            )}
            aria-hidden
          >
            {locked ? <Lock size={11} /> : selected ? <Check size={12} /> : null}
          </span>
        )}
      </div>
      <p className="flex-1 text-sm text-text-2">{agentDescription(agent, i18n.language)}</p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <LevelBadge level={agent.level} />
        {agent.mandatory && (
          <Badge tone="brand">
            <Lock size={10} /> {t('agents.mandatory')}
          </Badge>
        )}
        {recommendedReason && (
          <Badge tone="accent" className="max-w-full">
            <Sparkles size={10} /> {t('agents.recommended')}
          </Badge>
        )}
        <span className="ml-auto text-xs text-muted" title={t('agents.relativeCost')}>
          {'$'.repeat(agent.relativeCost)}
        </span>
      </div>
      {recommendedReason && <p className="mt-2 text-xs text-muted">{t(`wizard.reasons.${recommendedReason}`)}</p>}
      <p className="mt-1 text-xs text-muted">{t('agents.defaultModel', { profile: agent.defaultProfile })}</p>
      {modelWarning && (
        <p className="mt-1 flex items-start gap-1 text-xs text-warning-ink">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {modelWarning}
        </p>
      )}
    </div>
  )
}
