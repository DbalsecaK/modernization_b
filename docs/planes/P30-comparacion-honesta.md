# Plan de la precisión P30 — Comparación honesta con el legado

- **Estado:** cerrado (2026-10-06).
- **Fuente:** ADR-0044, D-63; análisis de las peticiones y respuestas guardadas de la corrida 44027f4f (dos rondas,
  nueve llamadas al desarrollador, ~8 USD sin acercarse).
- **Rama:** `p29-base-reevaluada-y-severidad`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Análisis de raíz con los artefactos guardados (`generation/convergence/attempt-N-*.md`, `findings.json`, golden master): el parámetro de salida nunca asignado (72/73 casos) y las llamadas borradas al rechazar |
| 2 | `GoldenMaster.unassigned_outputs` (detección estática Sybase, omitido al serializar si está vacío); `masks()` enmascara con eco confirmado |
| 3 | Arneses Java (tres variantes), .NET y Go: las llamadas previas a `BusinessError` se conservan |
| 4 | Grabador Sybase: la llamada se reporta al producirse (sobrevive al `rollback`); regrabación del fixture y de M4 con Sybase local |
| 5 | `progress_key` por severidad de los casos; `rebuild_base` reevalúa cada corrección conservada |
| 6 | Pruebas: adaptador Sybase, core, packs con Docker, orquestación, aceptación M4; ADR-0044, D-63 |

## 2. Cierre

Con la comparación honesta, las 47 diferencias de la corrida real deberían reducirse a las de lógica (código
122001 por tipo de cuenta, orden de llamadas en caminos de fallo, un concepto contable). La pregunta de escalado
se responde "reintentar" solo con esto en main.
