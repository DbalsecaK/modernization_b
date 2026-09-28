# CLAUDE.md

Instrucciones para Claude Code en este repositorio.

## Qué es este proyecto

Plataforma web multi-cliente de NexTI para modernizar aplicaciones legacy (COBOL, CICS/BMS, Sybase, ASPX)
y construir funcionalidades nuevas desde documentación y Figma, con agentes de IA verificados.

**La fuente de verdad es `docs/ESPECIFICACION_PLATAFORMA.md`.** Léela antes de cualquier tarea no trivial.
Si una tarea contradice la especificación, detente y pregunta; si la especificación cambia, actualízala en
el mismo cambio y registra la decisión (sección 22 y un ADR en `docs/adr/`, índice en `docs/adr/README.md`).

## Cómo trabajar

- Se trabaja **por hitos** (sección 20: M0, M1, …). No adelantes funcionalidad de hitos posteriores.
- Antes de implementar un hito, propone un plan corto (archivos, entidades, endpoints, tests) y espera
  confirmación.
- Un hito está terminado solo cuando se cumplen **todos** sus criterios de aceptación con tests automatizados.
- Cambios pequeños y revisables; un commit por unidad lógica, con mensajes descriptivos en español.

## Stack y estructura

- Frontend: `apps/web` (React + TypeScript + Vite).
- API: `apps/api` (Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic).
- Workers: `apps/worker` (LangGraph + LangChain).
- Paquetes Python compartidos en `packages/` (workspace `uv`). Ver estructura completa en la sección 19.3.
- Entorno local con `infra/docker-compose/`.
- **Prototipo del frontend ya construido** en `apps/web` (sección 18.7): todas las pantallas con datos
  simulados en `apps/web/src/mocks/`. Al implementar cada hito, reemplaza los mocks por la API real
  manteniendo los tipos; no reescribas las pantallas desde cero.
  - Formularios de alta/edición: panel lateral `Drawer` y avisos `toast` de `apps/web/src/components/ui/overlay.tsx`.
  - Preguntas del human in the loop: `apps/web/src/features/decisions/` (sección 10.4).
  - Grafo de conocimiento: `apps/web/src/features/projects/graph/` (sección 5.2.1).
  - Panel flotante de actividad de agentes: `apps/web/src/components/layout/AgentActivityPanel.tsx` (sección 18.8).
  - Backlog Jira/Azure DevOps y ciclo de bugs: `apps/web/src/features/projects/tabs/BacklogTab.tsx` (sección 7.6).
  - Referencias de UI y vínculo con Jira/ADO en el asistente: `apps/web/src/features/projects/ProjectSetupSections.tsx`;
    chat de cambios al prototipo: `apps/web/src/features/projects/PrototypeChat.tsx` (secciones 7.1 y 7.4).
  - Historias de usuario y plan de migración: `apps/web/src/features/projects/stories/`; la validación del plan
    es determinista en `apps/web/src/lib/migrationPlan.ts` y la de los criterios Gherkin en `apps/web/src/lib/gherkin.ts`
    (sección 7.7); ambas deben migrar al backend sin cambiar su comportamiento.

## Comandos del frontend

```bash
pnpm install            # en la raíz del repo
pnpm web:dev            # servidor de desarrollo (http://localhost:5173)
pnpm web:build          # typecheck + build
pnpm web:test           # tests (paridad de catálogos i18n) + chequeo de claves usadas
pnpm lint               # ESLint; pnpm format:check para Prettier
```

## Comandos de Python

```bash
uv sync --all-packages  # workspace uv: apps/api y packages/*
pnpm py:check           # Ruff, mypy estricto y pytest
pnpm api:dev            # API FastAPI en http://localhost:8100 (docs: /api/v1/docs)
pnpm db:migrate         # migraciones Alembic (rol platform_owner)
pnpm db:seed            # datos ficticios de desarrollo
```

## Reglas no negociables

1. **Multi-tenant siempre:** toda tabla de negocio lleva `tenant_id` con Row-Level Security. El tenant se
   deriva de la sesión, nunca de un parámetro del cliente. Todo acceso a Neo4j pasa por `packages/graph`.
2. **Ninguna llamada a un modelo fuera de `packages/model_gateway`.** El gateway aplica política, perfil,
   fallback, presupuesto y registra el consumo.
3. **La API no ejecuta agentes.** Encola trabajos para los workers.
4. **Nada generado por un modelo ni código de clientes se ejecuta fuera del sandbox.**
5. **El código subido por clientes es input no confiable** (prompt injection, zip bombs, path traversal).
6. **Los veredictos los calcula código determinista**, nunca un modelo. Los agentes de Control son obligatorios.
7. **Autorización en cada endpoint** (OpenFGA) y **auditoría** de toda acción sensible.
8. **Sin secretos en el repositorio.** Usar variables de entorno / Vault. No commitear `.env`.
9. **Prohibido commitear código o datos de clientes**, incluidas las aplicaciones de referencia.
10. Versiones de modelos siempre fijas (sin alias "latest").
11. **Autenticación solo con Keycloak** (sección 15.1): la plataforma nunca guarda contraseñas ni secretos
    de MFA ni implementa su propio login. El navegador nunca recibe tokens: el BFF los guarda y emite una
    cookie `httpOnly`. Keycloak autentica, OpenFGA autoriza. Se implanta por etapas (D-27, `docs/adr/0004`):
    en M0 Keycloak mínimo con cuentas locales; SSO, MFA y Organizations en M0b. El modo `dev-auth` (usuario
    sembrado sin contraseña) solo existe en desarrollo y tests, y la API no arranca con él en otro entorno.

## Calidad

- Python: Ruff (lint y formato), mypy estricto en `packages/`, pytest.
- TypeScript: ESLint, Prettier, Vitest; Playwright para end-to-end.
- Todo endpoint nuevo: test de autorización (acceso permitido y denegado) y test de aislamiento entre tenants.
- Ejecutar lint, tipos y tests antes de dar una tarea por terminada.

## Idioma

- **El producto es nativamente en inglés** (sección 18.6 de la especificación):
  - Textos de UI escritos en inglés como fuente (catálogo `en`); el español es una traducción (`es`).
    Nunca escribas textos visibles directamente en el componente: usa claves i18n y agrega ambas traducciones.
  - Idioma por defecto: inglés. Prompts de sistema, skills y catálogo base en inglés.
  - Mensajes de error de la API: código estable + texto en inglés.
- **Todo el desarrollo en inglés:** identificadores, comentarios, docstrings, logs, nombres de tablas,
  endpoints y textos por defecto. El español solo existe como traducción seleccionable por el usuario.
- Única excepción: la especificación y la documentación interna en `docs/`, y los mensajes de commit, en español.
