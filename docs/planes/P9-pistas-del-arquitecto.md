# Plan del paso 9 — Pistas del arquitecto

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0035 (precisión paso 9), D-80; plan aprobado (paso 9).
- **Rama:** `plan-9-pistas-arquitecto` (sobre el paso 8).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Sybase: `unassigned_outputs(files, program)` y `columns_read(files)` en el adaptador |
| 2 | `legacy_shape_problems`: salidas nunca asignadas mapeadas y columnas cargadas que faltan en la entidad |
| 3 | Prueba del diseño con el problema y su corrección; aceptaciones grabadas sin cambios |

## Cómo se valida

Prueba de generación (los dos problemas aparecen y desaparecen al corregir el diseño) y todas las aceptaciones
grabadas en verde.
