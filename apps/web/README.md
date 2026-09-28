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
| Projects → New project | 9-step wizard: recommended agent cards, skills with conflicts, models, autonomy level |
| Project → Inventory | Knowledge graph in two layouts (**Circles** and **Layers**): pick a **business flow** to walk it step by step, pick a **business rule** to focus it, click a node for its description and connections, show impact, filter relations, show **only orphans and isolated** nodes, zoom, pan and double-click to zoom in |
| Project → Source ↔ target | Legacy and target code side by side, the rule, and legacy vs new outputs |
| Project → Specification | Rules, screens, contracts and questions |
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
| `pnpm test` | i18n catalog parity tests + check that every key used in code exists |
| `pnpm typecheck` | TypeScript only |

## Structure

```
src/
├─ main.tsx, router.tsx        # Entry point and routes (TanStack Router, auth guard)
├─ styles.css                  # Design tokens (light/dark) + Tailwind
├─ i18n/                       # i18next setup; locales/en.json (source) and es.json
├─ lib/                        # format, session (mock), theme, recommendation rules, URL tabs
├─ mocks/                      # Sample data and domain types — replace with API calls
├─ components/                 # UI primitives, drawer/toasts (overlay), status badges, charts, app shell, top bar widgets
└─ features/
   ├─ auth/                    # Login (SSO + password), MFA, forgot password, invitation, account
   ├─ dashboard/               # Executive / delivery / admin perspectives
   ├─ projects/                # List, new-project wizard (agents & skills), workspace with 13 tabs
   │  ├─ graph/                # Knowledge graph: circles and layers layouts, flows, rule focus, filters, orphans, impact
   │  ├─ tabs/                 # Workspace tabs
   │  └─ InputForms.tsx        # Add inputs (files, Git, Figma, Jira) with security checks
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
