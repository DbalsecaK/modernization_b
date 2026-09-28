import { useEffect, useState, useSyncExternalStore, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Bot, CheckCircle2, ChevronDown, Download, Loader2, Maximize2, Minimize2, PauseCircle, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatUsd } from '@/lib/format'
import { activitySeed, projects, type ActivityEvent, type ActivityStatus } from '@/mocks/data'

// Live agent activity (spec 18.8). In the real platform events arrive over SSE from the workers; here a small
// simulation adds events so the panel can be evaluated. Newest events are always on top.

// Sample events are shifted to the recent past so live events (now) always sort on top.
function rebase(seed: ActivityEvent[]) {
  const latest = Math.max(...seed.map((e) => new Date(e.endedAt ?? e.startedAt).getTime()))
  const shift = Date.now() - 60_000 - latest
  const move = (iso?: string) => (iso ? new Date(new Date(iso).getTime() + shift).toISOString() : undefined)
  return seed.map((e) => ({ ...e, startedAt: move(e.startedAt)!, endedAt: move(e.endedAt) }))
}

let events: ActivityEvent[] = rebase(activitySeed)
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

function useEvents() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => events,
    () => events,
  )
}

const templates: { agent: string; projectId: string; message: string; seconds: number; cost: number; fail?: boolean; waiting?: boolean }[] = [
  { agent: 'Business rules extractor', projectId: 'p1', message: 'Extracting rules from shard BILL', seconds: 9, cost: 1.84 },
  { agent: 'Rules verifier', projectId: 'p1', message: 'Verifying 12 citations in shard BILL', seconds: 6, cost: 0.42 },
  { agent: 'Backend developer', projectId: 'p1', message: 'Fixing bug CARDS-112 (rounding in InterestCalculator)', seconds: 10, cost: 0.96 },
  { agent: 'Test engineer', projectId: 'p1', message: 'Re-running 412 tests from clean', seconds: 7, cost: 0.12 },
  { agent: 'UX/UI designer', projectId: 'p4', message: 'Regenerating prototype "Personal data" (v4)', seconds: 8, cost: 0.58 },
  { agent: 'Equivalence validator', projectId: 'p2', message: 'Comparing 14 fresh inputs with the legacy', seconds: 8, cost: 0.37, fail: true },
  { agent: 'Supervisor', projectId: 'p1', message: 'Gate C1 waiting for business approval', seconds: 3, cost: 0, waiting: true },
  { agent: 'Code reviewer', projectId: 'p1', message: 'Reviewing commit a91c2e4 for CARDS-107', seconds: 5, cost: 0.21 },
]

let simulationStarted = false
function startSimulation() {
  if (simulationStarted) return
  simulationStarted = true
  let i = 0
  window.setInterval(() => {
    const tpl = templates[i++ % templates.length]
    const id = `ev-${Date.now()}`
    const ev: ActivityEvent = { id, startedAt: new Date().toISOString(), agent: tpl.agent, projectId: tpl.projectId, message: tpl.message, status: 'running', costUsd: 0, tokens: 0 }
    events = [ev, ...events].slice(0, 60)
    emit()
    window.setTimeout(() => {
      events = events.map((e) =>
        e.id !== id
          ? e
          : {
              ...e,
              endedAt: new Date().toISOString(),
              status: tpl.waiting ? 'waiting' : tpl.fail ? 'failed' : 'succeeded',
              costUsd: tpl.cost,
              tokens: Math.round(tpl.cost * 180_000),
              error: tpl.fail
                ? { code: 'EQUIVALENCE_DIFF', message: 'Fresh input F11 differs from the legacy output', detail: 'legacy STATUS=S, new STATUS=SUSPENDED (no mapping declared for the status code)' }
                : undefined,
            },
      )
      emit()
    }, tpl.seconds * 1000)
  }, 6000)
}

function elapsed(ev: ActivityEvent, now: number) {
  const end = ev.endedAt ? new Date(ev.endedAt).getTime() : now
  const s = Math.max(0, Math.round((end - new Date(ev.startedAt).getTime()) / 1000))
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s` : `${s}s`
}

function timeOf(iso: string, lang: string) {
  return new Intl.DateTimeFormat(lang === 'es' ? 'es-EC' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(iso))
}

// Full event payload for offline analysis (what support needs to reproduce the failure).
function downloadJson(ev: ActivityEvent) {
  const project = projects.find((p) => p.id === ev.projectId)
  const payload = {
    event: ev,
    project: project ? { id: project.id, name: project.name } : ev.projectId,
    run: { id: 'run-0007', phase: 'verification', iteration: '1/3' },
    model: { profile: 'Independent review', offering: 'GPT (large) — NexTI — OpenAI API', effort: 'high' },
    trace: { id: `trace-${ev.id}`, url: `https://langfuse.example/trace/${ev.id}` },
    environment: { platformVersion: '0.2.0', agentVersion: '1.4.0', skills: ['golden-master@1.1.0'] },
    exportedAt: new Date().toISOString(),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `agent-event-${ev.id}.json`
  a.click()
  URL.revokeObjectURL(url)
}

const statusIcon: Record<ActivityStatus, ReactElement> = {
  running: <Loader2 size={14} className="animate-spin text-info" />,
  succeeded: <CheckCircle2 size={14} className="text-good" />,
  failed: <AlertTriangle size={14} className="text-critical" />,
  waiting: <PauseCircle size={14} className="text-warning" />,
}

type Mode = 'minimized' | 'open' | 'maximized'

export function AgentActivityPanel() {
  const { t, i18n } = useTranslation()
  const list = useEvents()
  const [mode, setMode] = useState<Mode>('minimized')
  const [filter, setFilter] = useState<'all' | ActivityStatus>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    startSimulation()
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const sorted = [...list].sort((a, b) => b.startedAt.localeCompare(a.startedAt))
  const running = sorted.filter((e) => e.status === 'running')
  const failed = sorted.filter((e) => e.status === 'failed')
  const total = sorted.reduce((s, e) => s + e.costUsd, 0)
  const latest = sorted[0]
  const shown = sorted.filter((e) => filter === 'all' || e.status === filter)

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
        {failed.length > 0 && <span className="rounded-full bg-critical/12 px-2 py-0.5 text-xs text-critical-ink">{failed.length}</span>}
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
        <span className="text-xs text-sidebar-text tabular">{t('activity.panel.summary', { running: running.length, cost: formatUsd(total, 2) })}</span>
        <button onClick={() => setMode(mode === 'open' ? 'maximized' : 'open')} className="rounded p-1 hover:bg-white/10" aria-label={t(mode === 'open' ? 'activity.panel.maximize' : 'activity.panel.restore')}>
          {mode === 'open' ? <Maximize2 size={14} /> : <Minimize2 size={14} />}
        </button>
        <button onClick={() => setMode('minimized')} className="rounded p-1 hover:bg-white/10" aria-label={t('activity.panel.minimize')}>
          <X size={14} />
        </button>
      </div>

      {latest && (
        <div className={cn('border-b border-border px-4 py-3', latest.status === 'failed' ? 'bg-critical/8' : latest.status === 'running' ? 'bg-info/8' : 'bg-surface-2')}>
          <div className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('activity.panel.latest')}</div>
          <div className="mt-1 flex items-center gap-2 text-sm">
            {statusIcon[latest.status]}
            <span className="font-semibold text-text">{latest.agent}</span>
            <span className="ml-auto text-xs text-muted tabular">{timeOf(latest.startedAt, i18n.language)}</span>
          </div>
          <p className="mt-0.5 text-sm text-text-2">{latest.message}</p>
          <div className="mt-1 flex gap-3 text-xs text-muted tabular">
            <span>{t('activity.panel.elapsed', { value: elapsed(latest, now) })}</span>
            <span>{formatUsd(latest.costUsd, 2)}</span>
            <span>{projects.find((p) => p.id === latest.projectId)?.name}</span>
          </div>
        </div>
      )}

      <div className="flex gap-1 border-b border-border px-3 py-2 text-xs">
        {(['all', 'running', 'failed', 'waiting', 'succeeded'] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f} className={cn('rounded-full px-2.5 py-1', filter === f ? 'bg-brand text-brand-contrast' : 'text-muted hover:bg-surface-2')}>
            {t(`activity.panel.filters.${f}`)}
          </button>
        ))}
      </div>

      <ul className="flex-1 divide-y divide-border overflow-y-auto">
        {shown.map((ev) => {
          const open = expanded === ev.id
          return (
            <li key={ev.id} className={cn(ev.status === 'failed' && 'bg-critical/5')}>
              <button onClick={() => setExpanded(open ? null : ev.id)} className="flex w-full items-start gap-2 px-4 py-2.5 text-left hover:bg-surface-2" aria-expanded={open}>
                <span className="mt-0.5">{statusIcon[ev.status]}</span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className="truncate text-sm font-medium text-text">{ev.agent}</span>
                    <span className="ml-auto shrink-0 text-[11px] text-muted tabular">{timeOf(ev.startedAt, i18n.language)}</span>
                  </span>
                  <span className="block truncate text-xs text-text-2">{ev.message}</span>
                  <span className="mt-0.5 flex gap-3 text-[11px] text-muted tabular">
                    <span>{t(`activity.panel.status.${ev.status}`)}</span>
                    <span>{elapsed(ev, now)}</span>
                    <span>{formatUsd(ev.costUsd, 2)}</span>
                  </span>
                </span>
                <ChevronDown size={14} className={cn('mt-1 shrink-0 text-muted transition-transform', open && 'rotate-180')} />
              </button>
              {open && (
                <div className="space-y-2 px-4 pb-3 pl-10 text-xs">
                  <div className="text-muted">{projects.find((p) => p.id === ev.projectId)?.name}</div>
                  <div className="text-muted tabular">{t('activity.panel.tokens', { value: ev.tokens.toLocaleString() })}</div>
                  {ev.error && (
                    <div className="rounded-md border border-critical/30 bg-critical/8 p-2">
                      <div className="font-mono text-critical-ink">{ev.error.code}</div>
                      <div className="text-text">{ev.error.message}</div>
                      <div className="mt-1 text-text-2">{ev.error.detail}</div>
                    </div>
                  )}
                  <button onClick={() => downloadJson(ev)} className={cn('inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1', ev.error ? 'border-critical/40 text-critical-ink' : 'border-border text-text-2')}>
                    <Download size={12} /> {t('activity.panel.downloadJson')}
                  </button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
