# Plan del hito M28 — Quirks del motor y entorno

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0048, D-77; plan aprobado (paso 6).
- **Rama:** `m28-quirks-y-entorno` (sobre M27b).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `EngineQuirk` y `EnvironmentItem` en el golden master (omitidos si están vacíos) |
| 2 | `SourceAdapter.engine_quirks`; Sybase con catálogo de 10 quirks, COBOL, ASPX y declarativos vacíos |
| 3 | `nexti_adapter_sybase.quirks`: detección por tokens, sondas, entorno del motor y del programa |
| 4 | `AseRunner._engine_facts`: sondas y entorno una vez por motor, en el mismo motor del golden master |
| 5 | Núcleo: casos por quirk (con la cobertura de ADR-0047), quirks sin caso, combinaciones severas, notas |
| 6 | Caracterización: los quirks sin caso en la ronda de M27b; resumen con el registro |
| 7 | Generación: notas del motor junto al programa; `docs/legacy-engine.md` en la entrega |
| 8 | Veredicto: quirks y combinaciones sin caso en "no probado" |
| 9 | Pruebas unitarias y en vivo con Sybase ASE 16 (todas las sondas confirmadas) |

## Consecuencias

- Un lote más por arranque del motor.
- El ADR del veredicto (paso 8 del plan) decidirá si un quirk sin caso bloquea PROVEN.

## Cómo se valida

Ver ADR-0048, sección "Cómo se valida". En vivo: las 9 sondas del catálogo responden lo esperado en ASE 16, el
entorno se mide completo (8 ajustes) y la grabación del ficticio se reproduce con la cobertura confiable.
