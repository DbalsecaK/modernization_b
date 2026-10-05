# Plan del hito M21 — Preferencias del proyecto

- **Estado:** cerrado (2026-10-05).
- **Fuente:** secciones 8.4, 7.7 y 6.1; ADR-0038 y D-57.
- **Rama:** `m21-preferencias-verificables` (sobre M20).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Catálogo: arquitectura `preserve-topology`, grupos `strategy`, `artifact`, `practices`; regla de compatibilidad `preserveTopologyWaves`; modelo `Preference` y validación `unknown_preference` |
| 2 | API y worker: `target.preferences` al crear y leer; el catálogo las expone; la corrida las recibe planas |
| 3 | Orientación (solo guiada): `stack_guidance` para el arquitecto, el planificador de historias y el desarrollador |
| 4 | Web: selectores de estrategia y artefacto, chips de prácticas con su aviso de orientativas |
| 5 | Pruebas de composición y de orientación; ADR-0038 y D-57 |

## 2. Cierre

La arquitectura, la estrategia y las prácticas llegan ahora a los agentes que las necesitan. Lo que no se puede
verificar queda dicho como orientativo en la pantalla y en el ADR.
