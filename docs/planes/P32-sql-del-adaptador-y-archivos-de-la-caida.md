# Plan de la precisión P32 — SQL del adaptador contra el esquema y archivos de la caída

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0042 (precisión P32), D-66; corrida completa desde inventario: 68 de 73 casos caídos en un
  adaptador que la convergencia no podía mostrar.
- **Rama:** `p32-sql-del-adaptador-y-archivos-de-la-caida`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `sqlprobe.py`: extracción de sentencias SQL del adaptador (literales y bloques de texto, `?` → `$n`), `PREPARE` en el sandbox con el esquema, informe por sentencia |
| 2 | `SpringBootPack.probe_sql` (PostgreSQL); Oracle, MySQL y MongoDB sin sonda por ahora; `_adapter.verify` la usa en modo guiado |
| 3 | `correction.failure_files`/`frame_of`: archivos de los marcos de pila en `files_to_correct`; marco en el resumen de diferencias |
| 4 | Pruebas: `test_sqlprobe.py` (extracción, informe, sonda en Docker con el adaptador de referencia y uno roto), `test_correction.py` |

## 2. Cierre

Validado con las suites de orquestación y del pack (Docker). La escalación abierta de la corrida se responde
"reintentar" con esto en main: la convergencia entrega el adaptador caído al desarrollador.
