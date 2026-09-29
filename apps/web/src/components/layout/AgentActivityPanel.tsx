import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  Download,
  Loader2,
  Maximize2,
  Minimize2,
  PauseCircle,
  X,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatUsd } from '@/lib/format'
import { useProjectList } from '@/api/projects'
import { downloadEvent, useActivityStream, type ActivityEvent } from '@/api/runs'
import { toast } from '@/components/ui/overlay'

// Live agent activity (spec 18.8): events arrive over SSE from the workers, only for the projects the user may see.
// Newest events are on top; each one can be downloaded as JSON without secrets (redacted by the server).

type Status = ActivityEvent['status']

function timeOf(iso: string, lang: string) {
  return new Intl.DateTimeFormat(lang === 'es' ? 'es-EC' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(iso))
}

const statusIcon: Record<string, ReactElement> = {
  running: <Loader2 size={14} className="animate-spin text-info" />,
  succeeded: <CheckCircle2 size={14} className="text-good" />,
  failed: <AlertTriangle size={14} className="text-critical" />,
  waiting: <PauseCircle size={14} className="text-warning" />,
}

type Mode = 'minimized' | 'open' | 'maximized'

const cost = (e: ActivityEvent) => Number(e.costUsd ?? 0)

export function AgentActivityPanel() {
  const { t, i18n } = useTranslation()
  const [mode, setMode] = useState<Mode>('minimized')
  const { events } = useActivityStream()
  const projects = useProjectList()
  const [filter, setFilter] = useState<'all' | Status>('all')
  const [expanded, setExpanded] = useState<number | null>(null)
  const projectName = (id: string) => projects.data?.find((p) => p.id === id)?.name ?? ''

  const running = events.filter((e) => e.status === 'running')
  const failed = events.filter((e) => e.status === 'failed')
  const total = events.reduce((s, e) => s + cost(e), 0)
  const latest = events[0]
  const shown = events.filter((e) => filter === 'all' || e.status === filter)
  const agent = (e: ActivityEvent) => e.agentKey ?? t('activity.panel.platform')

  const download = (id: number) => downloadEvent(id).catch(() => toast(t('common.error')))

  if (mode === 'minimized') {
    return (
      <button
        onClick={() => setMode('open')}
        className="fixed right-4 bottom-4 z-40 flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2.5 text-sm shadow-lg hover:bg-surface-2"
        aria-label={t('activity.panel.open')}
      >
        <Bot size={16} className="text-brand dark:text-accent" />
        <span className="font-medium text-text">{t('activity.panel.title')}</span>
        {running.length > 0 && (
          <span className="flex items-center gap-1 rounded-full bg-info/12 px-2 py-0.5 text-xs text-info">
            <Loader2 size={11} className="animate-spin" /> {running.length}
          </span>
        )}
        {failed.length > 0 && (
          <span className="rounded-full bg-critical/12 px-2 py-0.5 text-xs text-critical-ink">{failed.length}</span>
        )}
        <span className="text-xs text-muted tabular">{formatUsd(total, 2)}</span>
      </button>
    )
  }

  return (
    <div
      className={cn(
        'fixed z-40 flex flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl',
        mode === 'open' ? 'right-4 bottom-4 h-[520px] w-[400px] max-w-[calc(100vw-2rem)]' : 'inset-6 lg:inset-x-24',
      )}
      role="dialog"
      aria-label={t('activity.panel.title')}
    >
      <div className="flex items-center gap-2 border-b border-border bg-sidebar px-4 py-3 text-white">
        <Bot size={16} className="text-accent" />
        <span className="flex-1 text-sm font-semibold">{t('activity.panel.title')}</span>
        <span className="text-xs text-sidebar-text tabular">
          {t('activity.panel.summary', { running: running.length, cost: formatUsd(total, 2) })}
        </span>
        <button
          onClick={() => setMode(mode === 'open' ? 'maximized' : 'open')}
          className="rounded p-1 hover:bg-white/10"
          aria-label={t(mode === 'open' ? 'activity.panel.maximize' : 'activity.panel.restore')}
        >
          {mode === 'open' ? <Maximize2 size={14} /> : <Minimize2 size={14} />}
        </button>
        <button
          onClick={() => setMode('minimized')}
          className="rounded p-1 hover:bg-white/10"
          aria-label={t('activity.panel.minimize')}
        >
          <X size={14} />
        </button>
      </div>

      {latest && (
        <div
          className={cn(
            'border-b border-border px-4 py-3',
            latest.status === 'failed' ? 'bg-critical/8' : latest.status === 'running' ? 'bg-info/8' : 'bg-surface-2',
          )}
        >
          <div className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('activity.panel.latest')}</div>
          <div className="mt-1 flex items-center gap-2 text-sm">
            {statusIcon[latest.status]}
            <span className="font-semibold text-text">{agent(latest)}</span>
            <span className="ml-auto text-xs text-muted tabular">{timeOf(latest.occurredAt, i18n.language)}</span>
          </div>
          <p className="mt-0.5 text-sm text-text-2">{latest.message}</p>
          <div className="mt-1 flex gap-3 text-xs text-muted tabular">
            {latest.costUsd !== null && <span>{formatUsd(cost(latest), 2)}</span>}
            <span>{projectName(latest.projectId)}</span>
          </div>
        </div>
      )}

      <div className="flex gap-1 border-b border-border px-3 py-2 text-xs">
        {(['all', 'running', 'failed', 'waiting', 'succeeded'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            aria-pressed={filter === f}
            className={cn(
              'rounded-full px-2.5 py-1',
              filter === f ? 'bg-brand text-brand-contrast' : 'text-muted hover:bg-surface-2',
            )}
          >
            {t(`activity.panel.filters.${f}`)}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="p-6 text-center text-sm text-muted">{t('activity.panel.empty')}</p>
      ) : (
        <ul className="flex-1 divide-y divide-border overflow-y-auto">
          {shown.map((ev) => {
            const open = expanded === ev.id
            const error =
              (ev.payload as { error?: unknown; diagnostic?: string }).error ??
              (ev.payload as { diagnostic?: string }).diagnostic
            return (
              <li key={ev.id} className={cn(ev.status === 'failed' && 'bg-critical/5')}>
                <button
                  onClick={() => setExpanded(open ? null : ev.id)}
                  className="flex w-full items-start gap-2 px-4 py-2.5 text-left hover:bg-surface-2"
                  aria-expanded={open}
                >
                  <span className="mt-0.5">{statusIcon[ev.status]}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className="truncate text-sm font-medium text-text">{agent(ev)}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-muted tabular">
                        {timeOf(ev.occurredAt, i18n.language)}
                      </span>
                    </span>
                    <span className="block truncate text-xs text-text-2">{ev.message}</span>
                    <span className="mt-0.5 flex gap-3 text-[11px] text-muted tabular">
                      <span>{t(`activity.panel.status.${ev.status}`)}</span>
                      {ev.costUsd !== null && <span>{formatUsd(cost(ev), 2)}</span>}
                    </span>
                  </span>
                  <ChevronDown
                    size={14}
                    className={cn('mt-1 shrink-0 text-muted transition-transform', open && 'rotate-180')}
                  />
                </button>
                {open && (
                  <div className="space-y-2 px-4 pb-3 pl-10 text-xs">
                    <div className="text-muted">{projectName(ev.projectId)}</div>
                    {ev.phase && (
                      <div className="text-muted">{t(`phases.${ev.phase}`, { defaultValue: ev.phase })}</div>
                    )}
                    <div className="text-muted tabular">
                      {t('activity.panel.tokens', { value: ev.tokens.toLocaleString() })}
                    </div>
                    {error !== undefined && (
                      <div className="rounded-md border border-critical/30 bg-critical/8 p-2 font-mono break-words whitespace-pre-wrap text-text">
                        {typeof error === 'string' ? error : JSON.stringify(error)}
                      </div>
                    )}
                    <button
                      onClick={() => void download(ev.id)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1',
                        ev.status === 'failed' ? 'border-critical/40 text-critical-ink' : 'border-border text-text-2',
                      )}
                    >
                      <Download size={12} /> {t('activity.panel.downloadJson')}
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
