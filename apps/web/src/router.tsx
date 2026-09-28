import { createRootRoute, createRoute, createRouter, Outlet, redirect } from '@tanstack/react-router'
import { queryClient } from '@/api/queryClient'
import { canOpen, meQuery, type NavKey } from '@/api/session'
import { AppShell } from '@/components/layout/AppShell'
import { LoginPage } from '@/features/auth/LoginPage'
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

const tabSearch = (search: Record<string, unknown>): { tab?: string; rule?: string; view?: string } => ({
  tab: typeof search.tab === 'string' ? search.tab : undefined,
  rule: typeof search.rule === 'string' ? search.rule : undefined,
  view: typeof search.view === 'string' ? search.view : undefined,
})

const rootRoute = createRootRoute({ component: Outlet, notFoundComponent: NotFoundPage })

// Sign-in page. In M0 the credentials are entered on Keycloak's own pages; the prototype's MFA, password reset
// and invitation screens (features/auth) become the Keycloak theme in M0b (D-27) and are not routed.
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  validateSearch: (search: Record<string, unknown>): { redirect?: string; error?: string } => ({
    redirect: typeof search.redirect === 'string' ? search.redirect : undefined,
    error: typeof search.error === 'string' ? search.error : undefined,
  }),
  component: LoginPage,
})

// Authenticated area: the API says whether there is a session (httpOnly cookie).
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  beforeLoad: async ({ location }) => {
    const me = await queryClient.ensureQueryData(meQuery)
    if (!me) throw redirect({ to: '/login', search: { redirect: location.href } })
    return { me }
  },
  component: AppShell,
})

// Sections the user has no permission for redirect to the dashboard (the API denies the calls anyway).
const guard = (key: NavKey) => async () => {
  const me = await queryClient.ensureQueryData(meQuery)
  if (!canOpen(me, key)) throw redirect({ to: '/' })
}

const dashboardRoute = createRoute({ getParentRoute: () => appRoute, path: '/', component: DashboardPage })
const projectsRoute = createRoute({ getParentRoute: () => appRoute, path: '/projects', component: ProjectsPage })
const newProjectRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/projects/new',
  component: NewProjectWizard,
})
const projectRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/projects/$projectId',
  validateSearch: tabSearch,
  component: ProjectWorkspace,
})
const tasksRoute = createRoute({ getParentRoute: () => appRoute, path: '/tasks', component: TasksPage })
const usageRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/usage',
  beforeLoad: guard('usage'),
  component: UsagePage,
})
const aiConfigRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/ai-config',
  beforeLoad: guard('aiConfig'),
  validateSearch: tabSearch,
  component: AiConfigPage,
})
const catalogRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/catalog',
  validateSearch: tabSearch,
  component: CatalogPage,
})
const adminRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/admin',
  beforeLoad: guard('admin'),
  validateSearch: tabSearch,
  component: AdminPage,
})
const platformRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/platform',
  beforeLoad: guard('platform'),
  component: PlatformPage,
})
const accountRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/account',
  validateSearch: tabSearch,
  component: AccountPage,
})

const routeTree = rootRoute.addChildren([
  loginRoute,
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
