# Plan R2a — Ejecución del legado por proyecto y trazas de IBM i

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0052, D-84; plan de soporte RPG aprobado (R2).
- **Rama:** `r2a-ejecucion-del-legado` (sobre R1).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `nexti_core.legacy_execution`: modos, tipos de sistema, configuración de IBM i validada, credenciales |
| 2 | Migración 0026 `project_legacy_execution` con RLS; ruta del secreto `tenants/{t}/legacy/{p}` |
| 3 | API `/api/v1/projects/{id}/legacy-execution` (GET, PUT, `:test`, DELETE) con auditoría y guarda SSRF |
| 4 | Worker: `SourceRunner` elige por la configuración del proyecto; fábricas de runners en vivo por tipo |
| 5 | Motor `ibmi-trace` en `TRACE_ENGINES`; trazas ficticias de `ACTSALDO` con cobertura por subrutina |
| 6 | Web: tarjeta **Ejecución del legado** en Insumos (modernización y validación independiente) |

## 2. Fuera de R2a

El runner en vivo de IBM i (R2b).

## Cómo se valida

Pruebas del worker, de la API (incluidos los permisos) y del adaptador RPG; web con lint, tipos y pruebas.
