# Plan de la precisión P33 — Esquema a la vista y sonda de SQL en la convergencia

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0042 (precisión P33), D-67; ronda posterior a P32: el desarrollador reescribió tres veces el
  adaptador contra una tabla del legado sin ver el esquema ni el mensaje de la base de datos.
- **Rama:** `p33-esquema-y-sonda-en-la-convergencia`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `correction.failure_excerpt`: inicio y final del mensaje de una caída en el resumen |
| 2 | `pack.schema_path()`; esquema destino en la petición de convergencia cuando un adaptador está involucrado |
| 3 | `converge.verify`: `probe_sql` de cada adaptador corregido antes del golden master |
| 4 | Pruebas en `test_correction.py` y `test_fidelity.py` |
