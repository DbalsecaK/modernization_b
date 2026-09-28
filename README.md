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
