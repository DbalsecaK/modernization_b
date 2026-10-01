# Plataforma de Modernización NexTI

Plataforma web multi-cliente para:

1. **Modernizar** aplicaciones legacy (COBOL, CICS/BMS, Sybase, ASPX/.NET Framework) hacia stacks modernos,
   con extracción de reglas de negocio, generación desde la especificación y validación de equivalencia.
2. **Construir funcionalidades nuevas** desde documentos, historias de usuario, Figma y capturas.

Metodología: Spec-Driven Development, con agentes de IA orquestados en LangGraph, verificación
independiente y aprobaciones humanas.

El producto es **nativamente en inglés**, con cambio completo a español.

## Documentación

- [Especificación de la plataforma](docs/ESPECIFICACION_PLATAFORMA.md): visión, flujos, arquitectura,
  seguridad, RBAC, configuración IA, costos, frontend y roadmap por hitos.
- [Decisiones de arquitectura (ADR)](docs/adr/README.md): OpenFGA, Keycloak con Organizations, componentes
  UI y autenticación por etapas.
- [Plan del hito M0](docs/planes/M0-fundaciones.md): pasos, tablas, endpoints y tests de las fundaciones.
- [Plan del hito M1](docs/planes/M1-configuracion-ia.md): configuración IA, gateway de modelos y consumo.
- [Plan del hito M2](docs/planes/M2-proyectos-insumos.md): proyectos, catálogo de agentes y skills, insumos.
- [Plan del hito M3](docs/planes/M3-motor-orquestacion.md): motor de orquestación, worker, compuertas y preguntas.
- [CLAUDE.md](CLAUDE.md): instrucciones para trabajar con Claude Code.

## Estado

- Especificación maestra y decisiones registradas (`docs/ESPECIFICACION_PLATAFORMA.md`).
- Prototipo navegable de todas las pantallas en `apps/web` (inglés nativo, español, tema claro/oscuro), con
  datos simulados. Capturas en `docs/prototipo/`. Incluye, entre otros: grafo de conocimiento, comparación
  origen ↔ destino, preguntas del human in the loop, referencias de UI (capturas, Figma, prototipos) desde la
  creación del proyecto, chat de cambios al prototipo, backlog con Jira/Azure DevOps y ciclo automático de
  bugs, panel flotante de actividad de agentes, e historias de usuario editables con un plan de migración por
  olas sugerido por el sistema y modificable, validado contra las dependencias, con criterios de aceptación
  en Gherkin validados.
- **Hito M0 — Fundaciones terminado** (rama `m0-fundaciones`): API FastAPI con BFF y Keycloak (cuentas locales,
  cookie `httpOnly`, CSRF, dev-auth solo en desarrollo), multi-tenant con RLS, usuarios, invitaciones, roles y
  matriz de permisos con OpenFGA (outbox y reconciliación), auditoría inmutable con hash encadenado (incluidos los
  eventos de Keycloak), la web conectada en sesión, menú, cliente, idioma y Administración, primitivas sobre Radix,
  y CI con tests contra servicios reales, e2e con Playwright + axe, SAST, SCA y secret scanning. Criterios y
  evidencia: [docs/planes/M0-fundaciones.md](docs/planes/M0-fundaciones.md) (sección 15); capturas en `docs/m0/`.
  SSO con Entra ID, MFA y Organizations van en **M0b**.
- **Hito M1 — Configuración IA y consumo terminado** (rama `m1-configuracion-ia`): conexión OpenRouter por
  cliente con la API key en OpenBao (nunca en la base ni en el navegador), catálogo sincronizado con proveedores
  de destino y precios versionados, perfiles con esfuerzo normalizado y respaldo, cascada cliente → proyecto →
  fase → rol, políticas (prohibir OpenRouter, proveedores permitidos, ZDR), **gateway único**
  (`packages/model_gateway`) con libro de consumo append-only, presupuestos y alertas, y las pantallas de
  Configuración IA y Consumo y costos conectadas. Criterios y evidencia:
  [docs/planes/M1-configuracion-ia.md](docs/planes/M1-configuracion-ia.md) (sección 7); capturas en `docs/m1/`.
- **Hito M2 — Proyectos e insumos terminado** (rama `m2-proyectos-insumos`): catálogo de agentes y skills como datos
  versionados (`packages/agents`, `packages/skills`), motor determinista que propone el equipo y las skills con su
  motivo y valida la composición (Control obligatorio), asistente de creación y proyectos con configuración
  versionada, insumos validados por `packages/ingest` (tipo real, zip seguro, cabecera de imágenes, secretos,
  ClamAV, hash y versión) en MinIO, links de Figma y prototipos, y conexión Git sin SSRF. Criterios y evidencia:
  [docs/planes/M2-proyectos-insumos.md](docs/planes/M2-proyectos-insumos.md) (sección 7); capturas en `docs/m2/`.
- **Hito M3 — Motor de orquestación terminado** (rama `m3-motor-orquestacion`): worker (`apps/worker`) con cola
  Procrastinate sobre PostgreSQL y reanudación tras caída, grafo LangGraph compuesto desde la configuración con
  checkpointer PostgreSQL, compuertas C1–C4 con permiso y segregación de funciones, preguntas con respuesta
  recomendada, hacer → verificar → corregir con máximo de iteraciones y escalamiento, sandbox Docker sin red, preflight
  real y pipeline de demostración; en la web, pestaña Ejecuciones en vivo, Mis tareas, tarjetas de decisión y panel de
  actividad por SSE. Criterios y evidencia:
  [docs/planes/M3-motor-orquestacion.md](docs/planes/M3-motor-orquestacion.md) (sección 7); capturas en `docs/m3/`.
- Siguiente: **M4 — primera vertical**.

## Probar la aplicación

Con el entorno local levantado (ver Desarrollo):

```bash
pnpm api:dev      # API en http://localhost:8100
pnpm worker:dev   # worker de ejecuciones (cola Procrastinate, sandbox con el Docker local)
pnpm web:dev      # web en http://localhost:5173 (proxy de /api y /auth hacia la API)
```

El inicio de sesión va a Keycloak con los usuarios ficticios del realm (contraseña `KC_DEV_USER_PASSWORD` del
`.env`), o en desarrollo con `dev-auth` eligiendo un usuario sembrado. Todas las pantallas usan la API real (plan
P2), salvo las de hitos posteriores: la pestaña Backlog (M7b) y, en Administración, autenticación, seguridad e
integraciones del cliente (M0b, M7, M7b). En desarrollo, la pestaña Ejecuciones ofrece además el pipeline
de demostración, que ejercita el motor completo con el worker en marcha.

## Desarrollo

Requisitos: Node 24 con pnpm 10, Python 3.12 y [uv](https://docs.astral.sh/uv/).

```bash
pnpm install      # web y herramientas de lint
uv sync --all-packages
pnpm lint         # ESLint (apps/web)
pnpm format:check # Prettier (apps/web)
pnpm py:check     # Ruff, mypy estricto y pytest (apps/api, packages/)
pnpm api:dev      # API en http://localhost:8100 (/api/v1/health/ready, docs en /api/v1/docs)
```

### Entorno local (Docker Compose)

```bash
python infra/docker-compose/init_env.py        # crea .env con secretos aleatorios (repetir tras cada pull)
docker compose -f infra/docker-compose/compose.yaml up -d --wait
python infra/docker-compose/smoke_check.py     # verifica servicios, realm de Keycloak y roles de BD
pnpm db:migrate                                # esquema (Alembic, como platform_owner)
pnpm db:seed                                   # datos ficticios de desarrollo (idempotente) + reconciliación OpenFGA
uv run python -m nexti_api.cli catalog-sync    # carga el catálogo de agentes y skills (seed-dev ya lo hace)
pnpm fga:test                                  # tests del modelo de OpenFGA (infra/openfga)
pnpm authz:reconcile                           # iguala OpenFGA a lo que implica PostgreSQL
uv run python -m nexti_api.cli keycloak-events # copia los eventos de Keycloak a la auditoría (también en segundo plano)
pnpm api:types                                 # regenera los tipos TypeScript de la web desde el OpenAPI de la API
docker compose -f infra/docker-compose/compose.yaml --profile observability up -d --wait   # + Langfuse
```

Servicios en `127.0.0.1`: PostgreSQL 5440, Redis 6380, Keycloak 8180 (realm `nexti`), OpenFGA 8190, OpenBao 8210, ClamAV 3310,
Mailpit 8025, MinIO 9100/9101, Neo4j 7476/7689 y Langfuse 3100. Los puertos se cambian en `.env`.
Los usuarios de desarrollo del realm son ficticios (`admin@nexti.example`, `mtorres@andesbank.example`, …) y su
contraseña es `KC_DEV_USER_PASSWORD` del `.env`.

Para el test con la API real de OpenRouter (`test_openrouter_live.py`, unas millonésimas de dólar por corrida)
agrega `OPENROUTER_API_KEY_FOR_TESTS=<key>` al `.env` de `infra/docker-compose` (ignorado por git); sin ella el
test se omite. En CI se toma del secreto del mismo nombre.

ESLint y Prettier viven en `tools/lint` con su propio TypeScript 6: TypeScript 7 (compilador nativo) ya no
expone la API que usa typescript-eslint. La web sigue compilando con TypeScript 7.
