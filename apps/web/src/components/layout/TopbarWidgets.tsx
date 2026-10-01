import { useId, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Bell, Bot, FileText, FolderKanban, Puzzle, Search } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { useCatalog } from '@/api/projects'
import { useMe } from '@/api/session'
import { useDebounced, useNotifications, useSearchHits, type Notification } from '@/api/topbar'
import { agentName } from '@/features/catalog/AgentCard'
import { isUnread, matches, readSeen, writeSeen } from './topbarModel'

type Result = { kind: 'project' | 'rule' | 'agent' | 'skill'; id: string; label: string; hint: string; go: () => void }

const MAX_RESULTS = 10

// Global search (spec 18.1), connected to the API: projects and rules of the projects the user may see come from the
// server; agents and skills from the catalog the web already has.
export function GlobalSearch() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const me = useMe()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  const listId = useId()
  const settled = useDebounced(query.trim())
  const hits = useSearchHits(settled, !!me?.activeTenant)
  const catalog = useCatalog()

  const results = useMemo<Result[]>(() => {
    if (query.trim().length < 2) return []
    const server = (hits.data ?? []).map((h): Result => ({
      kind: h.kind,
      id: `${h.projectId}:${h.id}`,
      label: h.label,
      hint: h.kind === 'rule' ? h.hint : t('search.kinds.project'),
      go: () =>
        h.kind === 'project'
          ? navigate({ to: '/projects/$projectId', params: { projectId: h.projectId } })
          : navigate({
              to: '/projects/$projectId',
              params: { projectId: h.projectId },
              search: { tab: 'traceability', rule: h.id },
            }),
    }))
    const agents = (catalog.data?.agents ?? [])
      .filter((a) => matches(query, a.name, a.nameEs, a.key))
      .map((a): Result => ({
        kind: 'agent',
        id: a.key,
        label: agentName(a, i18n.language),
        hint: t(`agentGroups.${a.group}`),
        go: () => navigate({ to: '/catalog', search: { tab: 'agents' } }),
      }))
    const skills = (catalog.data?.skills ?? [])
      .filter((s) => matches(query, s.title, s.description, s.key))
      .map((s): Result => ({
        kind: 'skill',
        id: s.key,
        label: s.title,
        hint: t(`skillTypes.${s.type}`),
        go: () => navigate({ to: '/catalog', search: { tab: 'skills' } }),
      }))
    return [...server, ...agents, ...skills].slice(0, MAX_RESULTS)
  }, [query, hits.data, catalog.data, t, i18n.language, navigate])

  const icons = { project: FolderKanban, rule: FileText, agent: Bot, skill: Puzzle }

  function choose(r: Result) {
    r.go()
    setOpen(false)
    setQuery('')
  }

  return (
    <div
      ref={box}
      className="relative hidden max-w-md flex-1 sm:block"
      onBlur={(e) => {
        if (!box.current?.contains(e.relatedTarget as Node)) setOpen(false)
      }}
    >
      <Search size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" aria-hidden />
      <input
        className="h-9 w-full rounded-md border border-border bg-surface-2 pr-3 pl-9 text-sm text-text placeholder:text-muted focus:outline-none"
        placeholder={t('topbar.searchPlaceholder')}
        aria-label={t('topbar.search')}
        role="combobox"
        aria-controls={listId}
        aria-autocomplete="list"
        aria-expanded={open && results.length > 0}
        aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
          setActive(0)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') setActive((a) => Math.min(a + 1, results.length - 1))
          if (e.key === 'ArrowUp') setActive((a) => Math.max(a - 1, 0))
          if (e.key === 'Enter' && results[active]) choose(results[active])
          if (e.key === 'Escape') setOpen(false)
        }}
      />
      {open && query.trim().length >= 2 && (
        <div
          className="absolute top-11 right-0 left-0 z-30 rounded-lg border border-border bg-surface p-1 shadow-lg"
          id={listId}
          role="listbox"
          aria-label={t('topbar.search')}
        >
          {results.length === 0 ? (
            <p className="px-3 py-3 text-sm text-muted">
              {hits.isFetching ? t('search.searching') : t('search.noResults', { query })}
            </p>
          ) : (
            results.map((r, i) => {
              const Icon = icons[r.kind]
              return (
                <button
                  key={r.kind + r.id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(r)}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm',
                    i === active && 'bg-surface-2',
                  )}
                >
                  <Icon size={16} className="shrink-0 text-muted" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-text">{r.label}</span>
                    <span className="block truncate text-xs text-muted">{r.hint}</span>
                  </span>
                  <span className="text-xs text-muted">{t(`search.kinds.${r.kind}`)}</span>
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}

// Notifications (spec 18.1), connected to the API: derived from the user's tasks, escalations, finished runs, new
// verdicts and budget alerts. Which ones were read is remembered per viewer in this browser.
export function NotificationsMenu() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const me = useMe()
  const userId = me?.user.id ?? ''
  const [open, setOpen] = useState(false)
  // Read from storage once the session is known; marking all as read takes over from then on.
  const [marked, setMarked] = useState<string | null>(null)
  const seen = marked ?? (userId ? readSeen(userId) : null)
  const list = useNotifications(!!me?.activeTenant)
  const items = list.data ?? []
  const unread = items.filter((n) => isUnread(n, seen))

  function markAllRead() {
    const now = new Date().toISOString()
    writeSeen(userId, now)
    setMarked(now)
  }

  function openOne(n: Notification) {
    setOpen(false)
    if (n.projectId)
      void navigate({
        to: '/projects/$projectId',
        params: { projectId: n.projectId },
        search: { tab: n.tab ?? undefined },
      })
    else if (n.kind === 'budget') void navigate({ to: '/usage' })
    else void navigate({ to: '/tasks' })
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-md p-2 text-muted hover:bg-surface-2 hover:text-text"
        aria-label={t('topbar.notificationsCount', { count: unread.length })}
        aria-expanded={open}
      >
        <Bell size={18} aria-hidden />
        {unread.length > 0 && <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-critical" />}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-80 rounded-lg border border-border bg-surface shadow-lg sm:w-96">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-sm font-semibold text-text">{t('topbar.notifications')}</span>
            {unread.length > 0 && (
              <button className="text-xs font-medium text-brand hover:underline" onClick={markAllRead}>
                {t('notifications.markAllRead')}
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted">{t('notifications.empty')}</p>
          ) : (
            <ul className="max-h-96 divide-y divide-border overflow-y-auto" aria-label={t('topbar.notifications')}>
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    className="flex w-full gap-3 px-4 py-3 text-left hover:bg-surface-2"
                    onClick={() => openOne(n)}
                  >
                    <span
                      className={cn(
                        'mt-1.5 h-2 w-2 shrink-0 rounded-full',
                        isUnread(n, seen) ? 'bg-series-1' : 'bg-transparent',
                      )}
                      aria-hidden
                    />
                    <span className="min-w-0">
                      <span className="block text-sm text-text">
                        {t(`notifications.text.${n.kind}`, {
                          project: n.projectName ?? t('dashboard.tenantBudget'),
                          title: n.kind === 'escalation' ? t(`phases.${n.title}`, { defaultValue: n.title }) : n.title,
                        })}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted">
                        {t(`notifications.kinds.${n.kind}`)} · {formatDateTime(n.occurredAt)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
