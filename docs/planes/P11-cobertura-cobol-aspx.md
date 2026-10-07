# Plan del paso 11 — Cobertura del legado en COBOL y ASPX

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0047 (precisión paso 11), D-81; plan aprobado (paso 11).
- **Rama:** `plan-11-cobertura-cobol-aspx` (sobre el paso 10).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `CobolAdapter.coverage_branches`: los párrafos del programa |
| 2 | `AspxAdapter.coverage_branches`: los métodos del code-behind y de App_Code |
| 3 | Trazas: `executed` por resultado; `TraceRunner(branches=...)` arma la cobertura si todos los casos lo traen |
| 4 | El worker pasa al runner las ramas del adaptador del programa |
| 5 | Pruebas con trazas ficticias en COBOL y en ASPX |

## Cómo se valida

Con `executed` en cada caso, la cobertura dice qué párrafos o métodos se recorrieron; sin `executed` en alguno, o
sin adaptador, no se mide.
