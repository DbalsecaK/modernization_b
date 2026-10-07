# Plan del hito M29 — Cobertura del destino

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0049, D-78; plan aprobado (paso 7).
- **Rama:** `m29-cobertura-del-destino` (sobre M28).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Imágenes: JaCoCo en `nexti-sandbox-java`, `dotnet-coverage` en `nexti-sandbox-dotnet`; Go ya lo trae |
| 2 | Scripts de equivalencia de Spring Boot, .NET y Go: el arnés bajo la herramienta y el informe comprimido |
| 3 | `nexti_sandbox.coverage`: lectura de JaCoCo, Cobertura y perfil de Go a un formato neutro |
| 4 | Verificación: cobertura y regiones sin ejecutar en el veredicto; `TARGET_COVERAGE.json` en el paquete |
| 5 | Pruebas unitarias y en el sandbox real con el destino de referencia de cada pack |

## Consecuencias

- Las variantes de base de datos (Oracle, MySQL, MongoDB, Quarkus) quedan por extender con el mismo bloque.

## Cómo se valida

Ver ADR-0049, sección "Cómo se valida".
