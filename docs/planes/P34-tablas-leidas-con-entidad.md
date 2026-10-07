# Plan de la precisión P34 — Toda tabla leída se conserva o se enmascara

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0035 (precisión P34), D-68; corrida completa: 4 casos difirieron seis rondas porque dos tablas
  leídas por el programa no tenían entidad y sus filas nunca llegaron al destino.
- **Rama:** `p34-tablas-leidas-con-entidad`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `mask_problems`: tablas leídas sin entidad ni máscara → problema de diseño (solo guiado) |
| 2 | Prueba en `test_generation.py`; ADR-0035 (nota P34), D-68 |
| 3 | Reintento de la corrida desde Design (diseño nuevo con las tablas leídas) |
