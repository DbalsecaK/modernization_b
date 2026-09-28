import { useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Bell, Bot, FileText, FolderKanban, Puzzle, Search } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { agents, notifications, projects, rules, skills } from '@/mocks/data'
import { agentName } from '@/features/catalog/AgentCard'

type Result = { kind: 'project' | 'rule' | 'agent' | 'skill'; id: string; label: string; hint: string; go: () => void }

// Global search over projects, rules, agents and skills. The real version queries the API (and the graph).
export function GlobalSearch() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const box = useRef<HTMLDivElement>(null)

  const results = useMemo<Result[]>(() => {
    const q = query.trim().toLowerCase()
    if (q.length < 2) return []
    const match = (...values: string[]) => values.some((v) => v.toLowerCase().includes(q))
    return [
      ...projects
        .filter((p) => match(p.name, ...p.sources))
        .map((p) => ({
          kind: 'project' as const,
          id: p.id,
          label: p.name,
          hint: t(`flows.${p.flow}`),
          go: () => navigate({ to: '/projects/$projectId', params: { projectId: p.id } }),
        })),
      ...rules
        .filter((r) => match(r.id, r.name, r.source, r.domain))
        .map((r) => ({
          kind: 'rule' as const,
          id: r.id,
          label: `${r.id} · ${r.name}`,
          hint: r.source,
          go: () =>
            navigate({ to: '/projects/$projectId', params: { projectId: 'p1' }, search: { tab: 'specification' } }),
        })),
      ...agents
        .filter((a) => match(a.name, a.nameEs ?? ''))
        .map((a) => ({
          kind: 'agent' as const,
          id: a.id,
          label: agentName(a, i18n.language),
          hint: t(`agentGroups.${a.group}`),
          go: () => navigate({ to: '/catalog', search: { tab: 'agents' } }),
        })),
      ...skills
        .filter((s) => match(s.name, s.description))
        .map((s) => ({
          kind: 'skill' as const,
          id: s.id,
          label: s.name,
          hint: t(`skillTypes.${s.type}`),
          go: () => navigate({ to: '/catalog', search: { tab: 'skills' } }),
        })),
    ].slice(0, 10)
  }, [query, t, i18n.language, navigate])

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
      <Search size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
      <input
        className="h-9 w-full rounded-md border border-border bg-surface-2 pr-3 pl-9 text-sm text-text placeholder:text-muted focus:outline-none"
        placeholder={t('topbar.searchPlaceholder')}
        aria-label={t('topbar.search')}
        role="combobox"
        aria-expanded={open && results.length > 0}
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
          role="listbox"
        >
          {results.length === 0 ? (
            <p className="px-3 py-3 text-sm text-muted">{t('search.noResults', { query })}</p>
          ) : (
            results.map((r, i) => {
              const Icon = icons[r.kind]
              return (
                <button
                  key={r.kind + r.id}
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(r)}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm',
                    i === active && 'bg-surface-2',
                  )}
                >
                  <Icon size={16} className="shrink-0 text-muted" />
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

export function NotificationsMenu() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [read, setRead] = useState<string[]>([])
  const unread = notifications.filter((n) => n.unread && !read.includes(n.id))

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-md p-2 text-muted hover:bg-surface-2 hover:text-text"
        aria-label={t('topbar.notificationsCount', { count: unread.length })}
        aria-expanded={open}
      >
        <Bell size={18} />
        {unread.length > 0 && <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-critical" />}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-80 rounded-lg border border-border bg-surface shadow-lg sm:w-96">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-sm font-semibold text-text">{t('topbar.notifications')}</span>
            <button
              className="text-xs font-medium text-info hover:underline"
              onClick={() => setRead(notifications.map((n) => n.id))}
            >
              {t('notifications.markAllRead')}
            </button>
          </div>
          <ul className="max-h-96 divide-y divide-border overflow-y-auto">
            {notifications.map((n) => {
              const isUnread = n.unread && !read.includes(n.id)
              return (
                <li key={n.id}>
                  <button
                    className="flex w-full gap-3 px-4 py-3 text-left hover:bg-surface-2"
                    onClick={() => {
                      setRead([...read, n.id])
                      setOpen(false)
                      if (n.projectId)
                        void navigate({
                          to: '/projects/$projectId',
                          params: { projectId: n.projectId },
                          search: { tab: n.tab ?? undefined },
                        })
                      else void navigate({ to: '/ai-config' })
                    }}
                  >
                    <span
                      className={cn(
                        'mt-1.5 h-2 w-2 shrink-0 rounded-full',
                        isUnread ? 'bg-series-1' : 'bg-transparent',
                      )}
                      aria-hidden
                    />
                    <span className="min-w-0">
                      <span className="block text-sm text-text">{n.text}</span>
                      <span className="mt-0.5 block text-xs text-muted">
                        {t(`notifications.kinds.${n.kind}`)} · {formatDateTime(n.time)}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
