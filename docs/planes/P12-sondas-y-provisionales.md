# Plan del paso 12 — Sonda de SQL y servicio provisional en todos los packs

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0042 (precisión paso 12), D-82; plan aprobado (paso 12).
- **Rama:** `plan-12-sondas-y-provisionales` (sobre el paso 11).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Servicio provisional de .NET y Go |
| 2 | `nexti_sandbox.sqlprobe`: extracción por literales de cada lenguaje e informe por marcador o por línea |
| 3 | Sondas: MySQL y Oracle (Spring Boot), SQL Server y Oracle (.NET), PostgreSQL (Go) |
| 4 | Pruebas unitarias de extracción e informes; en el sandbox real, cada sonda acepta los adaptadores de referencia y nombra una tabla que falta |

## Cómo se valida

En cada sandbox, el adaptador de referencia prepara sin errores y uno que lee una tabla que el diseño no conserva
vuelve con el error y su sentencia; las pruebas de referencia compilan contra el servicio provisional.
