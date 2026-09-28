# Plan del hito M0 — Fundaciones

- **Estado:** aprobado el 2026-09-28 como **plan mixto**: este documento más tres enmiendas (ver abajo).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` (secciones 14, 15, 16, 18.7, 19, 20) y ADR-0001 a 0004.
- **Rama de trabajo:** `m0-fundaciones`, un commit por paso, PR a `main` al terminar.

**Enmiendas aprobadas**

1. **OpenFGA con `role_binding` por proyecto** (sección 6): asignar un rol de proyecto con `role:<id>#assignee`
   lo daría en todos los proyectos que usan ese rol; cada asignación de proyecto usa su propio objeto
   `role_binding:<proyecto>/<rol>`.
2. **Entorno local** (sección 3): versiones exactas verificadas, puertos alternativos solo en `127.0.0.1` (para no
   chocar con otros proyectos locales), Langfuse y ClickHouse en el perfil `observability` y secretos de
   desarrollo generados al azar por `infra/docker-compose/init_env.py` (el repositorio no tiene ni valores de ejemplo).
3. **Paso 1 ampliado** (sección 12): incluye la base de la API (settings, RFC 9457) y ESLint + Prettier, que
   estaban en los pasos 3 y 10.

## 1. Objetivo y alcance

Dejar lista la base sobre la que se construye todo lo demás: monorepo y CI, entorno local, API con sesión
segura, multi-tenant con RLS, módulo de usuarios y permisos con OpenFGA, auditoría y el prototipo conectado a
la API real en lo que toca a sesión y administración.

| Incluye | No incluye (hito) |
|---|---|
| Monorepo `uv` + `pnpm`, CI con lint, tipos, tests, SAST, SCA y secret scanning | Proyectos completos, asistente e insumos (M2) |
| Docker Compose con PostgreSQL, Neo4j, Redis, MinIO, Keycloak, OpenFGA, Langfuse y Mailpit | Configuración IA, gateway y consumo (M1) |
| API FastAPI con BFF, sesión en Redis, cookie `httpOnly`, CSRF y formato de errores RFC 9457 | Workers, LangGraph y agentes (M3) |
| Keycloak mínimo: realm importado, cuentas locales, invitación por correo (Mailpit en dev) | SSO, MFA, Organizations, Keycloakify (M0b) |
| Modo `dev-auth` solo en desarrollo y tests | Neo4j con datos (solo el servicio levantado; `packages/graph` en M4/M6) |
| Tenants, usuarios, membresías, roles, permisos, invitaciones y rol por proyecto, con RLS | |
| OpenFGA: modelo versionado, sincronización por outbox y reconciliación | |
| Auditoría append-only con hash encadenado | |
| Web: sesión real, menú por permisos, Administración (usuarios, invitaciones, roles, matriz, auditoría) con la API | |
| Primitivas de UI sobre shadcn/Radix sin cambiar su API, ESLint, Prettier, Playwright y axe | |

**Proyectos en M0:** el rol por proyecto necesita una tabla `project` mínima (id, tenant, nombre, estado).
Se crea con datos sembrados y sin pantallas de alta; el CRUD y el asistente son de M2.

## 2. Estructura de archivos

```
/
├─ pyproject.toml                  # workspace uv (miembros: apps/api, packages/core)
├─ uv.lock
├─ eslint.config.js, .prettierrc.json
├─ tools/lint/                     # ESLint y Prettier con TypeScript 6 propio (TS 7 no expone la API del compilador)
├─ .github/workflows/ci.yml
├─ apps/
│  ├─ api/
│  │  ├─ pyproject.toml
│  │  ├─ alembic.ini
│  │  ├─ migrations/               # Alembic: esquema, RLS, roles de BD, triggers de auditoría
│  │  ├─ src/nexti_api/
│  │  │  ├─ main.py                # app FastAPI, middlewares, arranque seguro (bloquea dev-auth fuera de dev/test)
│  │  │  ├─ settings.py            # pydantic-settings; APP_ENV, URLs, secretos por variables de entorno
│  │  │  ├─ db.py                  # engine, sesión por request, SET LOCAL app.tenant_id / app.user_id
│  │  │  ├─ errors.py              # Problem Details (código estable + mensaje en inglés)
│  │  │  ├─ auth/                  # bff.py (OIDC code + PKCE), session.py (Redis), csrf.py, dev_auth.py
│  │  │  ├─ authz/                 # openfga_client.py, require.py (dependencia por endpoint), outbox.py, reconcile.py
│  │  │  ├─ audit/                 # writer.py (hash encadenado), keycloak_events.py
│  │  │  └─ routers/               # health, auth, me, tenants, users, invitations, roles, permissions, projects, audit
│  │  └─ tests/                    # unit, integration (con servicios reales), authz, isolation
│  └─ web/                         # prototipo existente; se agregan api/, queries y tests e2e
├─ packages/
│  └─ core/                        # tipos compartidos: ids, enums de roles y permisos, errores (mypy estricto)
└─ infra/
   ├─ docker-compose/
   │  ├─ compose.yaml
   │  ├─ .env.example              # nombres de variables y puertos; secretos vacíos
   │  ├─ init_env.py               # crea .env con secretos aleatorios (y agrega los que falten)
   │  └─ postgres/init/01-roles-and-databases.sh   # bases y roles de BD (lee las contraseñas del entorno)
   ├─ keycloak/realm-nexti.json    # realm de desarrollo: cliente del BFF, usuarios de prueba sin datos reales
   ├─ openfga/model.fga            # modelo de autorización
   └─ openfga/model.tests.yaml     # tests del modelo (permitido/denegado)
```

## 3. Entorno local (Docker Compose)

| Servicio | Imagen (fijada) | Puerto local (`127.0.0.1`) | Para qué en M0 |
|---|---|---|---|
| postgres | `postgres:17.11` | 5440 | Base de la plataforma, de Keycloak, de OpenFGA y de Langfuse |
| redis | `redis:8.8.3-alpine` | 6380 | Sesiones del BFF |
| keycloak | `quay.io/keycloak/keycloak:26.7.4` | 8180 | Autenticación (realm importado al arrancar) |
| openfga | `openfga/openfga:v1.21.0` | 8190 | Autorización |
| mailpit | `axllent/mailpit:v1.31.3` | 8025 (UI), 1025 (SMTP) | Correos de invitación en desarrollo |
| minio | `cgr.dev/chainguard/minio@sha256:…` (MinIO ya no publica imágenes comunitarias) | 9100/9101 | Solo levantado (se usa en M2) |
| neo4j | `neo4j:5.26.31-community` | 7476/7689 | Solo levantado (se usa en M4/M6; D-12 pendiente) |
| langfuse + clickhouse | `langfuse:4.46.0`, `clickhouse-server:25.12.11.4` | 3100 | Perfil `observability`, solo levantado (se usa en M1/M3) |

La API de desarrollo usa el puerto 8100. Todos los puertos se pueden cambiar en `.env`.

```bash
python infra/docker-compose/init_env.py        # crea .env con secretos aleatorios
docker compose -f infra/docker-compose/compose.yaml up -d --wait
docker compose -f infra/docker-compose/compose.yaml --profile observability up -d --wait   # con Langfuse
```

`.env` nunca se commitea; `.env.example` solo tiene nombres y puertos.

## 4. Modelo de datos (PostgreSQL)

Identificadores en inglés, `uuid` como clave, `created_at`/`updated_at` en UTC.

| Tabla | Columnas principales | Tenant / RLS |
|---|---|---|
| `tenant` | id, slug, name, status, deployment_model, created_at | Sin RLS; solo la lee la API con el rol de plataforma o vía membresía |
| `app_user` | id, keycloak_sub (único), email, display_name, locale, status, last_login_at | Global (un usuario puede pertenecer a varios tenants); **sin columnas de contraseña** |
| `membership` | id, tenant_id, user_id, status (invited/active/suspended), created_by | RLS por `tenant_id` |
| `role` | id, tenant_id (NULL = rol de sistema), scope (platform/tenant/project), key, name, is_system | RLS: `tenant_id = actual OR tenant_id IS NULL` (solo lectura para los de sistema) |
| `permission` | key (p. ej. `users.manage`, `gate.c1.approve`), scope, description | Catálogo global de solo lectura (16.2) |
| `role_permission` | role_id, permission_key | Hereda del rol |
| `role_assignment` | id, tenant_id, user_id, role_id, project_id (NULL = rol de tenant) | RLS por `tenant_id` |
| `project` | id, tenant_id, name, status | RLS por `tenant_id` (mínima; CRUD en M2) |
| `invitation` | id, tenant_id, email, role_id, project_id, status, expires_at, invited_by | RLS por `tenant_id`; sin tokens propios (el correo lo envía Keycloak) |
| `authz_outbox` | id, tenant_id, operation (write/delete), tuples (jsonb), status, attempts, created_at | RLS por `tenant_id` |
| `audit_log` | id, tenant_id (NULL = evento de plataforma), occurred_at, actor_id, actor_kind (user/dev-auth/system/keycloak), action, target, outcome, details (jsonb), prev_hash, hash | Append-only: sin UPDATE/DELETE (REVOKE + trigger); RLS de lectura por `tenant_id` |

**Cómo quedó implementado (paso 4)**

- `tenant` y `app_user` también tienen RLS: un tenant ve el activo y aquellos donde el usuario tiene membresía;
  un usuario ve a sí mismo y a los usuarios del tenant activo. Durante el login, `app.auth_sub` y
  `app.auth_email` dejan ver solo al usuario que entra y sus invitaciones pendientes.
- Los roles son **por tenant**: al crear un tenant se copian los roles base de `nexti_core.authz_catalog`
  (`is_system = true`), que su administrador puede editar. Las claves son las del prototipo (`tenantAdmin`,
  `projectOwner`, …) y los permisos las de 16.2 en inglés (`users.manage`, …).
- `permission_scope` indica si un permiso se da a nivel tenant, proyecto o ambos; claves foráneas compuestas
  garantizan que rol, tenant, alcance, proyecto y membresía sean coherentes.
- Los roles de plataforma (`superAdmin`, `supportOperator`) van en `platform_role_assignment`: sin RLS y de solo
  lectura para la API.
- `ensure_user_for_invitation()` (SECURITY DEFINER) permite invitar a una persona que ya existe en otro tenant sin
  exponer su fila.

**RLS y roles de base de datos**

- La API se conecta con el rol `platform_app` (sin `BYPASSRLS`, dueño de nada); las migraciones con
  `platform_owner`. El publicador del outbox usa `authz_relay`, que solo puede leer y actualizar `authz_outbox`
  (con su propia política RLS, sin `BYPASSRLS`).
- Cada request abre una transacción y ejecuta `SET LOCAL app.tenant_id = '<tenant de la sesión>'` y
  `SET LOCAL app.user_id = '<usuario>'`. Las políticas usan `current_setting('app.tenant_id', true)::uuid`.
- Sin tenant en la sesión, las consultas a tablas con RLS no devuelven filas (fallo seguro).
- `FORCE ROW LEVEL SECURITY` en todas las tablas de negocio.

**Roles de sistema sembrados (16.1):** `platform.superadmin`, `platform.support`, `tenant.admin`,
`tenant.auditor`, `tenant.finance`, `project.owner`, `project.architect`, `project.analyst`,
`project.business_reviewer`, `project.developer`, `project.observer`, con los paquetes de permisos de 16.2.

## 5. Autenticación (BFF + Keycloak mínimo, D-27)

| Endpoint | Qué hace |
|---|---|
| `GET /auth/login?returnTo=` | Genera `state`, `nonce` y PKCE, redirige a Keycloak |
| `GET /auth/callback` | Canjea el código, valida el ID token, crea o actualiza `app_user` por `sub`, activa invitaciones pendientes del correo, crea la sesión en Redis y emite la cookie |
| `POST /auth/logout` | Borra la sesión, hace logout en Keycloak (end session) y audita |
| `GET /api/v1/me` | Usuario, tenants a los que pertenece, tenant activo y permisos efectivos (para el menú) |
| `PUT /api/v1/session/tenant` | Cambia el tenant activo; valida la membresía activa (el tenant nunca se toma de un parámetro en las demás llamadas) |
| `GET /auth/dev/users` · `POST /auth/dev/login` | Solo `APP_ENV=development/test`: lista usuarios sembrados y abre sesión sin contraseña; audita con `actor_kind=dev-auth` |

- **Cookie:** `__Host-nexti_session`, `HttpOnly`, `Secure` (en dev sobre `localhost`), `SameSite=Lax`, `Path=/`.
  Solo contiene un id aleatorio; los tokens de Keycloak quedan en Redis.
- **Sesión:** inactividad 30 min y máximo 12 h (15.1), rotación del id al iniciar sesión, revocación inmediata.
- **CSRF:** token por sesión entregado en `GET /api/v1/me` y exigido en el header `X-CSRF-Token` en toda
  petición que modifica datos; además se valida `Origin`.
- **Arranque seguro:** si `DEV_AUTH_ENABLED=true` y `APP_ENV` no es `development` ni `test`, la API no arranca.
- **Invitaciones:** el administrador invita (correo, rol, proyecto opcional) → la API crea el usuario en
  Keycloak vía Admin REST API con una cuenta de servicio de mínimo privilegio y pide a Keycloak el correo
  "definir contraseña" (llega a Mailpit en dev) → al primer login la membresía pasa a activa.
- **Implementado (paso 6):** el `state` es de un solo uso y queda atado al navegador con una cookie
  `__Host-nexti_login` (evita el login CSRF y el replay del callback). El ID token se valida con firma (JWKS),
  `iss` público, `aud`, `azp`, `exp` y `nonce`. Al primer login el usuario se enlaza por correo **verificado**;
  sin usuario de plataforma el acceso se rechaza (`no_platform_access`). En Redis la clave es el SHA-256 del id
  de sesión y el registro va cifrado. El logout termina también la sesión de Keycloak por back channel.
  `PATCH /api/v1/me` guarda el idioma. **Movido:** la activación de invitaciones al login pasa al paso 9 (con
  las invitaciones) y `me.permissions` se llena desde OpenFGA en el paso 8.
- **Realm de desarrollo:** `infra/keycloak/realm-nexti.json` con el cliente confidencial del BFF, política
  de contraseña básica y usuarios de prueba ficticios (`admin@nexti.example`, `po@andes.example`, …).

## 6. Autorización (OpenFGA, D-15)

**Modelo (`infra/openfga/model.fga`, borrador):**

```
model
  schema 1.1

type user

type platform
  relations
    define superadmin: [user]
    define support: [user]

# Tenant-scope role of one tenant: role:<tenant>/<role_key>
type role
  relations
    define assignee: [user]

# Project-scope role assignment, one object per project and role: role_binding:<project>/<role_key>
type role_binding
  relations
    define assignee: [user]

type tenant
  relations
    define platform: [platform]
    define member: [user]
    define admin: [user] or superadmin from platform
    # one relation per tenant permission (16.2), granted to roles:
    define users_manage: [role#assignee] or admin
    define audit_view: [role#assignee] or admin
    define cost_view: [role#assignee] or admin

type project
  relations
    define tenant: [tenant]
    define member: [role_binding#assignee]
    define view: member or admin from tenant
    define configure: [role_binding#assignee] or admin from tenant
    define gate_c1_approve: [role_binding#assignee]
    # ... resto de permisos de proyecto de 16.2
```

- **Roles de tenant:** se asignan con `role:<tenant>/<rol>#assignee@user:<id>` y cada permiso del rol se escribe
  como `tenant:<id>#<permiso>@role:<tenant>/<rol>#assignee`. `tenant.admin` se escribe directo en `admin`.
- **Roles de proyecto (enmienda 1):** asignar el rol R al usuario U en el proyecto P escribe
  `role_binding:P/R#assignee@user:U` y, por cada permiso de R, `project:P#<permiso>@role_binding:P/R#assignee`.
  Con `role:R#assignee` la asignación valdría en todos los proyectos que usan R. Cambiar la matriz de un rol de
  proyecto reescribe sus tuplas en cada proyecto del tenant, por outbox.
- `admin from tenant` no alcanza a `signoff_sign` (16.3: el administrador no firma si no es miembro con ese
  permiso). La segregación de funciones de las compuertas llega con M3.
- **Sincronización:** cada cambio en `role_assignment`, `role_permission` o `membership` inserta la fila de
  negocio y una fila en `authz_outbox` en la **misma transacción**; un proceso en la API publica el outbox en
  OpenFGA con reintentos. Un job de **reconciliación** compara PostgreSQL con OpenFGA y corrige.
- **En cada endpoint:** dependencia `require("users_manage", tenant)` / `require("configure", project)` con
  el usuario y el tenant de la sesión; una denegación devuelve 403 con código estable y se audita.
- **Listados:** `ListObjects` para "¿qué proyectos puede ver este usuario?".
- **Tests del modelo** en `model.tests.yaml`, ejecutados en CI con `fga model test`.
- **Implementado (paso 8):** `expected_tuples()` deriva desde PostgreSQL el estado deseado de cada tenant (solo
  membresías activas producen tuplas, así suspender revoca todo). `authz_change()` calcula ese estado antes y
  después de cada cambio y guarda la diferencia en el outbox en la misma transacción. El relay (tarea de fondo de
  la API, rol `authz_relay`) publica en orden y se detiene en el primer fallo; las escrituras son idempotentes
  (`on_duplicate`/`on_missing`). La reconciliación (periódica y `pnpm authz:reconcile`) compara todo el store y
  audita cada corrección. `model.json` se genera del `.fga` con la CLI y se versiona; en desarrollo el store se
  crea o actualiza al arrancar, fuera de él se fijan `OPENFGA_STORE_ID` y `OPENFGA_MODEL_ID`.
  Dependencias: `require_tenant`, `require_project`, `require_platform` y `authenticated` (marcadas para el
  meta-test del paso 9); `/me.permissions` sale de un batch check.

## 7. Endpoints de M0 (`/api/v1`)

| Recurso | Operaciones | Permiso |
|---|---|---|
| `health` | `GET /health/live`, `GET /health/ready` (comprueba Postgres, Redis, Keycloak, OpenFGA) | Público |
| `me`, `session` | Ver arriba | Sesión |
| `tenants` | `GET`, `POST`, `PATCH /{id}` | `platform.superadmin` (lista propia de tenants para el resto vía `me`) |
| `users` | `GET` (del tenant activo), `GET /{id}`, `PATCH /{id}` (estado, nombre), `DELETE /{id}/membership` | `users_manage` |
| `invitations` | `GET`, `POST`, `POST /{id}:resend`, `DELETE /{id}` | `users_manage` |
| `roles` | `GET`, `POST` (rol propio del tenant), `PATCH /{id}`, `DELETE /{id}` (no los de sistema) | `users_manage` |
| `roles/{id}/permissions` | `PUT` (matriz de permisos) | `users_manage` |
| `permissions` | `GET` (catálogo) | Sesión |
| `role-assignments` | `GET`, `POST`, `DELETE /{id}` (rol de tenant o de proyecto) | `users_manage` o `configure` del proyecto |
| `projects` | `GET` (solo los visibles, vía `ListObjects`) | `view` |
| `audit` | `GET` con filtros y paginación, `GET /export` | `audit_view` |

Errores en formato **RFC 9457** con `code` estable y `detail` en inglés. OpenAPI generado por FastAPI y
cliente TypeScript generado desde él para la web.

## 8. Auditoría

- `audit.write(action, target, outcome, details)` en un único módulo; calcula
  `hash = sha256(prev_hash + contenido canónico)` por tenant.
- Se auditan: login, logout, dev-auth, cambio de tenant activo, invitaciones, cambios de roles, permisos y
  membresías, denegaciones de autorización, cambios de tenants.
- **Eventos de Keycloak** (login, error, cambio de contraseña, admin events) llegan por un endpoint interno o
  por lectura periódica de la Admin API y se registran con `actor_kind=keycloak`.
- Verificación: `GET /api/v1/audit/verify` (solo auditor/superadmin) recorre la cadena y reporta cortes.
- **Implementado (paso 5):** la cadena la calcula un trigger de la base (`seq` sin huecos, `prev_hash`, `hash` =
  sha256 del JSON canónico de la fila), serializado por cadena con un advisory lock; una cadena por tenant y
  una de plataforma (`tenant_id` NULL). UPDATE, DELETE y TRUNCATE los rechaza un trigger incluso al dueño.
  `audit_verify(tenant)` detecta filas alteradas, reescritas o borradas. El escritor rechaza `details` con
  claves de credenciales o JWT, y el evento se registra en la misma transacción que la acción.

## 9. Frontend (`apps/web`)

- **Cliente de API:** `src/api/` con `fetch` (`credentials: 'include'`, header CSRF), tipos generados desde
  OpenAPI y **TanStack Query**. Los tipos de `src/mocks/types.ts` se mantienen y se mapean desde la API.
- **Sesión:** `src/lib/session.ts` pasa a leer `GET /api/v1/me`; sin sesión, redirige a `/auth/login`. En dev,
  pantalla simple para elegir un usuario de `dev-auth`. Las pantallas de login/MFA del prototipo no se usan
  hasta M0b.
- **Menú y rutas por permisos** a partir de `me.permissions`.
- **Administración conectada a la API:** usuarios, invitaciones, roles, matriz de permisos, auditoría. Las
  pestañas de identidad, SSO y políticas quedan con aviso "disponible en M0b".
- **Selector de cliente** de la barra superior conectado a `PUT /session/tenant`.
- **Primitivas sobre Radix (D-14):** `Drawer`, `Select`, `Tabs`, `Tooltip`, `Toast` (y Combobox cuando se
  toque), sin cambiar su API.
- **Calidad:** ESLint + Prettier (configuración nueva), Vitest (tests actuales), **Playwright** e2e y **axe**.
- i18n: toda clave nueva en `en.json` y `es.json` (el test de paridad lo exige).

## 10. CI (`.github/workflows/ci.yml`)

| Job | Qué corre |
|---|---|
| `python` | `uv sync`, `ruff check`, `ruff format --check`, `mypy` (estricto en `packages/`), `pytest` con servicios de Compose |
| `web` | `pnpm install`, ESLint, Prettier check, `tsc`, `pnpm web:test`, `pnpm web:build` |
| `openfga` | `fga model test` sobre `infra/openfga/model.tests.yaml` |
| `e2e` | Compose + API + web, Playwright (login con Keycloak, dev-auth, administración, axe) |
| `security` | Secret scanning (gitleaks), SCA (`pip-audit`, `pnpm audit`), SAST (Semgrep) |

## 11. Criterios de aceptación de M0 → tests

| Criterio (sección 20) | Test |
|---|---|
| Un usuario de un tenant no puede ver datos de otro (API y SQL) | `tests/isolation/`: por cada endpoint, un usuario de A no ve ni modifica datos de B (404/403); a nivel SQL, con `app.tenant_id` de A, `SELECT` sobre cada tabla con RLS no devuelve filas de B; sin `app.tenant_id`, no devuelve nada |
| Login con cuenta local de Keycloak y logout | e2e: login real contra Keycloak, `me` responde, logout invalida la sesión y la cookie |
| Ningún token llega al navegador | e2e: ni cookies, ni `localStorage`, ni respuestas JSON contienen `access_token`, `id_token`, `refresh_token` ni un JWT |
| La plataforma no guarda contraseñas | Test sobre el esquema: ninguna columna con nombre o contenido de contraseña/secreto; revisión de migraciones |
| La API no arranca con `dev-auth` fuera de dev/test | Test de arranque con `APP_ENV=production` + `DEV_AUTH_ENABLED=true` → falla |
| Test de autorización permitido y denegado por endpoint | `tests/authz/`: tabla de endpoints × roles con resultado esperado; un test que falla si un router no tiene `require(...)` |
| Un cambio de rol se refleja en OpenFGA; la reconciliación corrige | Integración: asignar rol → `check` permitido; quitar → denegado; borrar una tupla a mano → reconciliación la repone |
| Toda acción sensible queda en la auditoría (incluido Keycloak) | Integración: cada acción de la lista de la sección 8 genera su registro; la cadena de hashes verifica; UPDATE/DELETE sobre `audit_log` fallan |
| La web arranca en inglés; sin textos sin traducir en español; la preferencia persiste | Tests actuales de paridad + e2e de cambio de idioma y recarga |
| Las primitivas migradas pasan accesibilidad | Playwright + axe sin violaciones serias en login dev, dashboard y administración |

## 12. Pasos y commits (orden propuesto)

| # | Paso | Listo cuando |
|---|---|---|
| 1 ✅ | Monorepo: workspace uv con `apps/api` y `packages/core`, Ruff, mypy, pytest; base de la API (settings, errores RFC 9457); ESLint + Prettier en la web (enmienda 3) | `pnpm py:check`, `pnpm lint`, `pnpm format:check`, `pnpm web:test` en verde |
| 2 ✅ | `infra/docker-compose` con todos los servicios, healthchecks, roles de BD, `init_env.py` y realm de Keycloak de desarrollo | `docker compose up -d --wait` y todos *healthy* |
| 3 ✅ | API: logs estructurados, `/health/live` y `/health/ready`, OpenAPI | `GET /health/ready` = 200 con todos los servicios |
| 4 ✅ | Esquema con Alembic: tenancy, usuarios, roles, permisos, asignaciones, proyecto mínimo, invitaciones, outbox; RLS y roles de BD; datos sembrados | Tests SQL de aislamiento en verde |
| 5 ✅ | Auditoría append-only con hash encadenado y verificación | Tests de inmutabilidad y cadena en verde |
| 6 ✅ | BFF con Keycloak: login, callback, logout, sesión Redis, cookie, CSRF, `me`, cambio de tenant | Login real en local; test "ningún token en el navegador" |
| 7 ✅ | `dev-auth` y arranque seguro | Test de arranque en producción falla como se espera |
| 8 ✅ | OpenFGA: modelo y tests del modelo, cliente, `require(...)`, outbox y reconciliación | `fga model test` y tests de sincronización en verde |
| 9 | Routers de administración (tenants, usuarios, invitaciones con Keycloak + Mailpit, roles, matriz, asignaciones, proyectos, auditoría) con tests permitido/denegado y aislamiento | Suite `authz` e `isolation` en verde |
| 10 | Web: cliente de API, TanStack Query, sesión real, menú por permisos, selector de tenant | La web entra con Keycloak o dev-auth y muestra el menú según el rol |
| 11 | Web: Administración conectada (usuarios, invitaciones, roles, matriz, auditoría); reemplazo de mocks | e2e de invitar, asignar rol y ver auditoría |
| 12 | Primitivas sobre Radix + Playwright/axe | Tests de accesibilidad en verde, sin cambios en imports de pantallas |
| 13 | CI completo (jobs de la sección 10) | Pipeline verde en el PR |
| 14 | Cierre: recorrido de todos los criterios, actualización de spec/README/CLAUDE.md, capturas | Checklist de la sección 11 completo |

## 13. Decisiones menores a confirmar antes de empezar

| Tema | Propuesta |
|---|---|
| Tabla `project` mínima en M0 (necesaria para el rol por proyecto) | Sí, sin pantallas de alta (CRUD en M2) |
| Sesiones del BFF | Redis, con id aleatorio en la cookie |
| Invitaciones en dev | Correo real de Keycloak capturado por **Mailpit** (sin SMTP externo) |
| Eventos de Keycloak a la auditoría | Lectura periódica de la Admin API en M0; listener SPI si hace falta en M0b |
| Publicación del outbox | Tarea en segundo plano dentro de la API en M0 (sin cola todavía; la cola es D-13, M3) |
| Cliente TypeScript | Generado desde OpenAPI (`openapi-typescript`) |
| Versiones | Fijadas en `compose.yaml` (sección 3) y `.python-version` (3.12) |

## 14. Riesgos

| Riesgo | Mitigación |
|---|---|
| Olvidar `SET LOCAL app.tenant_id` en alguna ruta | La sesión de BD solo se obtiene por una dependencia que lo fija; test que falla si una consulta corre sin tenant |
| Divergencia entre PostgreSQL y OpenFGA | Outbox transaccional + reconciliación + test de diferencia forzada |
| Endpoint sin autorización | Test que recorre las rutas registradas y exige `require(...)` o marca explícita de público |
| Secretos en el repo | `.env` en `.gitignore`, gitleaks en CI, realm de dev sin secretos reales |
| Alcance de M0 crece (SSO, MFA) | Fuera de alcance explícito: M0b |
