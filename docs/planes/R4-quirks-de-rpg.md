# Plan R4 — Quirks de RPG

- **Estado:** cerrado (2026-10-08).
- **Fuente:** ADR-0048 (precisión R4), D-86; plan de soporte RPG aprobado.
- **Rama:** `r4-quirks-de-rpg`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Parser: medio ajuste de la columna 53 (RPG III), indicadores resultantes, nivel de control, archivo primario, palabras clave de control |
| 2 | `nexti_adapter_rpg.quirks`: catálogo de 15 quirks con su detección y el entorno que fija el programa |
| 3 | `RpgAdapter.engine_quirks` y `program_quirks`; el runner de IBM i los adjunta al golden master |
| 4 | Worker: un golden master de trazas sin quirks recibe los del adaptador |

## Cómo se valida

Pruebas del catálogo sobre los programas ficticios y programas inventados (todas las reglas), del runner de IBM i y
del worker con las trazas de `ACTSALDO`.
