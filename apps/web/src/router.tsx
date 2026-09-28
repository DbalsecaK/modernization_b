import { createRootRoute, createRoute, createRouter, Outlet, redirect } from '@tanstack/react-router'
import { getSession } from '@/lib/session'
import { AppShell } from '@/components/layout/AppShell'
import { LoginPage } from '@/features/auth/LoginPage'
import { MfaPage } from '@/features/auth/MfaPage'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { AcceptInvitePage } from '@/features/auth/AcceptInvitePage'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { ProjectsPage } from '@/features/projects/ProjectsPage'
import { NewProjectWizard } from '@/features/projects/NewProjectWizard'
import { ProjectWorkspace } from '@/features/projects/ProjectWorkspace'
import { TasksPage } from '@/features/tasks/TasksPage'
import { UsagePage } from '@/features/usage/UsagePage'
import { AiConfigPage } from '@/features/ai-config/AiConfigPage'
import { CatalogPage } from '@/features/catalog/CatalogPage'
import { AdminPage } from '@/features/admin/AdminPage'
import { PlatformPage } from '@/features/platform/PlatformPage'
import { AccountPage } from '@/features/auth/AccountPage'
import { NotFoundPage } from '@/features/NotFoundPage'

const tabSearch = (search: Record<string, unknown>): { tab?: string; rule?: string } => ({
  tab: typeof search.tab === 'string' ? search.tab : undefined,
  rule: typeof search.rule === 'string' ? search.rule : undefined,
})

const rootRoute = createRootRoute({ component: Outlet, notFoundComponent: NotFoundPage })

// Public authentication routes.
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => ({
    redirect: typeof search.redirect === 'string' ? search.redirect : undefined,
  }),
  component: LoginPage,
})
const mfaRoute = createRoute({ getParentRoute: () => rootRoute, path: '/login/mfa', component: MfaPage })
const forgotRoute = createRoute({ getParentRoute: () => rootRoute, path: '/forgot-password', component: ForgotPasswordPage })
const inviteRoute = createRoute({ getParentRoute: () => rootRoute, path: '/accept-invite', component: AcceptInvitePage })

// Authenticated area.
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  beforeLoad: ({ location }) => {
    if (!getSession()) throw redirect({ to: '/login', search: { redirect: location.href } })
  },
  component: AppShell,
})

const dashboardRoute = createRoute({ getParentRoute: () => appRoute, path: '/', component: DashboardPage })
const projectsRoute = createRoute({ getParentRoute: () => appRoute, path: '/projects', component: ProjectsPage })
const newProjectRoute = createRoute({ getParentRoute: () => appRoute, path: '/projects/new', component: NewProjectWizard })
const projectRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/projects/$projectId',
  validateSearch: tabSearch,
  component: ProjectWorkspace,
})
const tasksRoute = createRoute({ getParentRoute: () => appRoute, path: '/tasks', component: TasksPage })
const usageRoute = createRoute({ getParentRoute: () => appRoute, path: '/usage', component: UsagePage })
const aiConfigRoute = createRoute({ getParentRoute: () => appRoute, path: '/ai-config', validateSearch: tabSearch, component: AiConfigPage })
const catalogRoute = createRoute({ getParentRoute: () => appRoute, path: '/catalog', validateSearch: tabSearch, component: CatalogPage })
const adminRoute = createRoute({ getParentRoute: () => appRoute, path: '/admin', validateSearch: tabSearch, component: AdminPage })
const platformRoute = createRoute({ getParentRoute: () => appRoute, path: '/platform', component: PlatformPage })
const accountRoute = createRoute({ getParentRoute: () => appRoute, path: '/account', validateSearch: tabSearch, component: AccountPage })

const routeTree = rootRoute.addChildren([
  loginRoute,
  mfaRoute,
  forgotRoute,
  inviteRoute,
  appRoute.addChildren([
    dashboardRoute,
    projectsRoute,
    newProjectRoute,
    projectRoute,
    tasksRoute,
    usageRoute,
    aiConfigRoute,
    catalogRoute,
    adminRoute,
    platformRoute,
    accountRoute,
  ]),
])

export const router = createRouter({ routeTree, defaultPreload: 'intent' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
