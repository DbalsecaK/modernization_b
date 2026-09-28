# CLAUDE.md

Instrucciones para Claude Code en este repositorio.

## Qué es este proyecto

Plataforma web multi-cliente de NexTI para modernizar aplicaciones legacy (COBOL, CICS/BMS, Sybase, ASPX)
y construir funcionalidades nuevas desde documentación y Figma, con agentes de IA verificados.

**La fuente de verdad es `docs/ESPECIFICACION_PLATAFORMA.md`.** Léela antes de cualquier tarea no trivial.
Si una tarea contradice la especificación, detente y pregunta; si la especificación cambia, actualízala en
el mismo cambio y registra la decisión (sección 22 o un ADR en `docs/adr/`).

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

## Calidad

- Python: Ruff (lint y formato), mypy estricto en `packages/`, pytest.
- TypeScript: ESLint, Prettier, Vitest; Playwright para end-to-end.
- Todo endpoint nuevo: test de autorización (acceso permitido y denegado) y test de aislamiento entre tenants.
- Ejecutar lint, tipos y tests antes de dar una tarea por terminada.

## Idioma

- Documentación, mensajes de commit y textos de UI en español (con i18n para inglés).
- Identificadores de código en inglés.
