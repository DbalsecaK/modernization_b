# Plan del hito M27a — Cobertura del legado

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0047, D-75; plan aprobado (paso M27a).
- **Rama:** `m27a-cobertura-del-legado` (sobre 3b).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `Coverage`/`CoveredBranch` en el golden master (omitido si no se mide) |
| 2 | `nexti_adapter_sybase.coverage`: ramas e instrumentación de una copia; ramas no medibles declaradas |
| 3 | `AseRunner._cover`: segunda pasada en el mismo motor; caso no confiable si la copia difiere |
| 4 | Resumen de caracterización y "no probado" del veredicto con la cobertura y las ramas sin caso |
| 5 | Pruebas unitarias, de mutación del detector (pack Java) y en vivo con Sybase (24 de 26 ramas, 12 casos confiables) |
