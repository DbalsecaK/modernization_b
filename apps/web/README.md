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
├─ components/                 # UI primitives, status badges, charts, app shell
└─ features/
   ├─ auth/                    # Login (SSO + password), MFA, forgot password, invitation, account
   ├─ dashboard/               # Executive / delivery / admin perspectives
   ├─ projects/                # List, new-project wizard (agents & skills), workspace with 13 tabs
   ├─ tasks/                   # Cross-project approvals inbox
   ├─ usage/                   # Tokens and costs
   ├─ ai-config/               # Connections, catalog, profiles & effort, assignment, pricing, policies
   ├─ catalog/                 # Agent cards, skills, adapters, packs, compatibility, templates
   ├─ admin/                   # Customers, users, roles, authentication, security, integrations, audit
   └─ platform/                # Platform operations (NexTI only)
```

## Rules

- Never hard-code visible text: add a key to `en.json` and its translation to `es.json`.
- Status colors always come with an icon and a label.
- All data shown here is sample data. Company and person names are fictional; model IDs and prices are
  placeholders.
