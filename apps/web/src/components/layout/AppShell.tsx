import { useState } from 'react'
import { Link, Outlet, useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import {
  BookOpen,
  Bot,
  Building2,
  ChevronDown,
  CircleDollarSign,
  FolderKanban,
  Inbox,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Server,
  Settings2,
  Sun,
  UserRound,
  X,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { signOut, useSession } from '@/lib/session'
import { setTheme, useTheme } from '@/lib/theme'
import { setLanguage } from '@/i18n'
import { currentUser, tasks, tenants } from '@/mocks/data'
import { Avatar } from '@/components/ui/primitives'
import { Toaster } from '@/components/ui/overlay'
import { GlobalSearch, NotificationsMenu } from './TopbarWidgets'
import { AgentActivityPanel } from './AgentActivityPanel'

const nav = [
  { to: '/', key: 'dashboard', Icon: LayoutDashboard },
  { to: '/projects', key: 'projects', Icon: FolderKanban },
  { to: '/tasks', key: 'tasks', Icon: Inbox, badge: tasks.length },
  { to: '/usage', key: 'usage', Icon: CircleDollarSign },
  { to: '/ai-config', key: 'aiConfig', Icon: Bot },
  { to: '/catalog', key: 'catalog', Icon: BookOpen },
  { to: '/admin', key: 'admin', Icon: Settings2 },
  { to: '/platform', key: 'platform', Icon: Server },
] as const

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-baseline font-semibold tracking-tight', className)}>
      <span>nex</span>
      <span className="text-accent">TI</span>
    </span>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation()
  return (
    <nav className="flex h-full flex-col bg-sidebar text-sidebar-text" aria-label={t('nav.main')}>
      <div className="flex h-16 items-center gap-2 px-5">
        <Logo className="text-xl text-white" />
        <span className="text-xs text-sidebar-text/80">{t('app.productShort')}</span>
      </div>
      <ul className="flex-1 space-y-0.5 px-3 py-2">
        {nav.map(({ to, key, Icon, ...rest }) => (
          <li key={to}>
            <Link
              to={to}
              onClick={onNavigate}
              activeOptions={{ exact: to === '/' }}
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-white/5 hover:text-white"
              activeProps={{ className: 'bg-sidebar-active text-white font-medium' }}
            >
              <Icon size={18} aria-hidden />
              <span className="flex-1">{t(`nav.${key}`)}</span>
              {'badge' in rest && rest.badge ? (
                <span className="rounded-full bg-accent px-1.5 text-xs font-semibold text-[#052158]">{rest.badge}</span>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
      <div className="border-t border-white/10 px-5 py-4 text-xs text-sidebar-text/70">
        {t('app.version', { version: '0.1.0' })}
      </div>
    </nav>
  )
}

function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  return (
    <div className="flex rounded-md border border-border p-0.5 text-xs" role="group" aria-label={t('topbar.language')}>
      {(['en', 'es'] as const).map((lng) => (
        <button
          key={lng}
          onClick={() => setLanguage(lng)}
          aria-pressed={i18n.language === lng}
          className={cn(
            'rounded px-2 py-1 font-medium uppercase',
            i18n.language === lng ? 'bg-brand text-brand-contrast' : 'text-muted hover:text-text',
          )}
        >
          {lng}
        </button>
      ))}
    </div>
  )
}

function ThemeToggle() {
  const { t } = useTranslation()
  const theme = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      onClick={() => setTheme(next)}
      className="rounded-md p-2 text-muted hover:bg-surface-2 hover:text-text"
      aria-label={t('topbar.switchTheme', { theme: t(`topbar.theme.${next}`) })}
    >
      {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}

function UserMenu() {
  const { t } = useTranslation()
  const session = useSession()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-md p-1 hover:bg-surface-2"
        aria-expanded={open}
      >
        <Avatar initials={currentUser.initials} />
        <ChevronDown size={14} className="hidden text-muted sm:block" />
      </button>
      {open && (
        <div
          className="absolute right-0 z-30 mt-2 w-64 rounded-lg border border-border bg-surface p-2 shadow-lg"
          onMouseLeave={() => setOpen(false)}
        >
          <div className="px-3 py-2">
            <div className="text-sm font-medium text-text">{currentUser.name}</div>
            <div className="truncate text-xs text-muted">{session?.email ?? currentUser.email}</div>
            <div className="mt-1 text-xs text-muted">
              {session?.method === 'sso'
                ? t('auth.signedInWithSso', { provider: session.provider })
                : t('auth.signedInWithPassword')}
            </div>
          </div>
          <Link
            to="/account"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-text hover:bg-surface-2"
          >
            <UserRound size={16} /> {t('nav.account')}
          </Link>
          <button
            onClick={() => {
              signOut()
              void navigate({ to: '/login' })
            }}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-text hover:bg-surface-2"
          >
            <LogOut size={16} /> {t('auth.signOut')}
          </button>
        </div>
      )}
    </div>
  )
}

export function AppShell() {
  const { t } = useTranslation()
  const [mobileOpen, setMobileOpen] = useState(false)
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 lg:block">
        <Sidebar />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </div>
          <button
            className="absolute top-4 left-68 text-white"
            onClick={() => setMobileOpen(false)}
            aria-label={t('common.close')}
          >
            <X />
          </button>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-border bg-surface px-4 sm:px-6">
          <button
            className="rounded-md p-2 text-muted hover:bg-surface-2 lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label={t('nav.open')}
          >
            <Menu size={20} />
          </button>
          <div className="hidden items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-sm md:flex">
            <Building2 size={16} className="text-muted" />
            <select
              className="bg-transparent text-text focus:outline-none"
              aria-label={t('topbar.tenant')}
              defaultValue="all"
            >
              <option value="all">{t('topbar.allTenants')}</option>
              {tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
          </div>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden rounded-full border border-warning/50 px-2 py-0.5 text-xs text-warning-ink xl:inline">
              {t('app.sampleData')}
            </span>
            <LanguageSwitcher />
            <ThemeToggle />
            <NotificationsMenu />
            <UserMenu />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto px-4 pt-6 pb-24 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <Toaster />
        <AgentActivityPanel />
      </div>
    </div>
  )
}
