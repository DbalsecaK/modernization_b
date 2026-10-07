# Plan de la precisión P37 — Tablas homónimas en bases distintas

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0035 (precisión P37), D-71; último caso distinto de la corrida tras P36.
- **Rama:** `p37-tablas-con-otra-calificacion`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `qualified` y `homonym_tables` (inventario del adaptador); regla en `mask_problems` (solo guiado) |
| 2 | Prueba en `test_generation.py`; ADR-0035 (nota P37), D-71 |
| 3 | Reintento de la corrida desde Design |
