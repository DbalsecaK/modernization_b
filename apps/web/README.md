# NexTI Modernization Platform — Web

Navigable prototype of every screen in the platform specification
(`docs/ESPECIFICACION_PLATAFORMA.md`, section 18). English is the native language; users can switch to
Spanish at any time. Light and dark themes.

## Run

```bash
pnpm install          # from the repository root
pnpm web:dev          # http://localhost:5173
```

Sign in with any email. Domain `andesbank.example` shows the "SSO only" flow; any other email and a
password of 8+ characters goes to the MFA step (any 6 digits).

## What to try

| Where | What |
|---|---|
| Login | Email-first sign-in with SSO detection, password + MFA, forgot password, invitation |
| Projects → New project | 9-step wizard: recommended agent cards, skills with conflicts, models, autonomy level. The **Source** step also takes documents, **screenshots** (thumbnails), **Figma links** and **prototype links**, and links the project to **Jira or Azure DevOps** |
| Project → Inventory | Knowledge graph in two layouts (**Circles** and **Layers**): pick a **business flow** to walk it step by step, pick a **business rule** to focus it, click a node for its description and connections, show impact, filter relations, show **only orphans and isolated** nodes, zoom, pan and double-click to zoom in |
| Project → Source ↔ target | Legacy and target code side by side, the rule, and legacy vs new outputs |
| Project → Specification | Rules, screens, contracts and questions |
| Project → Specification → User stories | The stories that will be built, by feature: Gherkin criteria, links to rules / screens / contracts / legacy components, coverage gaps, versions. **Edit, create, split, merge, discard** (with a reason or as out of scope) and restore; accept or dismiss agent suggestions; approve with the plan at C1. Switch "Acting as" to see the permissions. Each **acceptance criterion is checked as Gherkin** (Given → When → Then, one behavior per scenario, outlines with examples; English or Spanish keywords): open **US-008** to see an invalid one, or type in the editor to see the errors live |
| Project → Specification → Migration plan | Waves **suggested** from the dependencies; drag stories or use the arrows. A move before a **hard** dependency is rejected; before a **soft** one it is allowed with an ACL/stub warning. Suggested vs yours, back to the suggested order |
| Project → Inputs → Add input | Files, Git, **screenshots**, Figma, **prototype link**, Jira / Azure DevOps (JQL or WIQL), with security checks |
| Project → UI design | Design system, prototype, **references** (add screenshots, Figma, prototypes) and the **prototype chat**: ask the UX/UI designer agent for a change and get a new version |
| Project → Backlog | Jira / Azure DevOps connection, type mapping, automation rules, feature → story → task → bug tree and the **bug loop** (tester opens the bug, developer fixes it, re-test) |
| Any screen → Agent activity | Floating copilot-style panel (bottom right): minimize, open, maximize; newest event on top with agent, elapsed time and cost; expand a failed event and **download its full JSON** |
| My tasks → Questions | Decision cards: recommended answer pre-selected, alternatives, "Other answer…", bulk accept low-impact |
| AI configuration | Add a Foundry / Bedrock / OpenAI connection, test it, discover models; profiles with effort |
| Catalog | Agent cards; create an agent or a skill |
| Administration | Customers, invitations, editable permission matrix, identity providers (Keycloak), policies |
| Top bar | Global search, notifications, EN/ES and light/dark |

## Scripts

| Command | What it does |
|---|---|
| `pnpm dev` | Development server |
| `pnpm build` | Typecheck + production build |
| `pnpm test` | i18n catalog parity tests, migration-plan rules, Gherkin checks + check that every key used in code exists |
| `pnpm typecheck` | TypeScript only |

## Structure

```
src/
├─ main.tsx, router.tsx        # Entry point and routes (TanStack Router, auth guard)
├─ styles.css                  # Design tokens (light/dark) + Tailwind
├─ i18n/                       # i18next setup; locales/en.json (source) and es.json
├─ lib/                        # format, session (mock), theme, recommendation rules, URL tabs,
│                              #   migrationPlan.ts (deterministic waves and dependency checks) and gherkin.ts
│                              #   (acceptance-criteria checks), both with tests
├─ mocks/                      # Sample data and domain types — replace with API calls
├─ components/                 # UI primitives, drawer/toasts (overlay), status badges, charts, app shell, top bar widgets,
│                              #   floating agent activity panel (layout/AgentActivityPanel.tsx)
└─ features/
   ├─ auth/                    # Login (SSO + password), MFA, forgot password, invitation, account
   ├─ dashboard/               # Executive / delivery / admin perspectives
   ├─ projects/                # List, new-project wizard (agents & skills), workspace with 14 tabs
   │  ├─ stories/              # User stories (edit, split, merge, discard) and migration plan by waves
│  ├─ graph/                # Knowledge graph: circles and layers layouts, flows, rule focus, filters, orphans, impact
   │  ├─ tabs/                 # Workspace tabs
   │  ├─ InputForms.tsx        # Add inputs (files, Git, screenshots, Figma, prototypes, Jira/ADO) with security checks
│  ├─ ProjectSetupSections.tsx # Wizard source step: documents, UI references, Jira/Azure DevOps link
│  └─ PrototypeChat.tsx     # Chat with the UX/UI designer agent to change the prototype
   ├─ decisions/               # Human-in-the-loop decision cards and their shared store
   ├─ tasks/                   # Cross-project approvals inbox
   ├─ usage/                   # Tokens and costs
   ├─ ai-config/               # Connections (+ form), catalog, profiles & effort, assignment, pricing, policies
   ├─ catalog/                 # Agent cards, skills (+ create forms), adapters, packs, compatibility, templates
   ├─ admin/                   # Customers, users, roles, authentication (+ forms), security, integrations, audit
   └─ platform/                # Platform operations (NexTI only)
```

## Rules

- Never hard-code visible text: add a key to `en.json` and its translation to `es.json`.
- Status colors always come with an icon and a label.
- All data shown here is sample data. Company and person names are fictional; model IDs and prices are
  placeholders.
