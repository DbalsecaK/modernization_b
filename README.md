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
- Siguiente paso: hito **M0 — Fundaciones** (Keycloak mínimo con cuentas locales, multi-tenant, usuarios y
  permisos con OpenFGA, auditoría, CI). SSO con Entra ID, MFA y Organizations van en **M0b**.

## Probar el prototipo

```bash
pnpm install
pnpm web:dev      # http://localhost:5173
```

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
pnpm fga:test                                  # tests del modelo de OpenFGA (infra/openfga)
pnpm authz:reconcile                           # iguala OpenFGA a lo que implica PostgreSQL
docker compose -f infra/docker-compose/compose.yaml --profile observability up -d --wait   # + Langfuse
```

Servicios en `127.0.0.1`: PostgreSQL 5440, Redis 6380, Keycloak 8180 (realm `nexti`), OpenFGA 8190,
Mailpit 8025, MinIO 9100/9101, Neo4j 7476/7689 y Langfuse 3100. Los puertos se cambian en `.env`.
Los usuarios de desarrollo del realm son ficticios (`admin@nexti.example`, `mtorres@andesbank.example`, …) y su
contraseña es `KC_DEV_USER_PASSWORD` del `.env`.

ESLint y Prettier viven en `tools/lint` con su propio TypeScript 6: TypeScript 7 (compilador nativo) ya no
expone la API que usa typescript-eslint. La web sigue compilando con TypeScript 7.
