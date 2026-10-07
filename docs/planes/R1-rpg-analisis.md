# Plan R1 — RPG / IBM i: análisis

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0051, D-83; plan de soporte RPG aprobado (R1–R4).
- **Rama:** `r1-rpg-analisis` (sobre el paso 12).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Paquete `nexti-adapter-rpg`: parser de RPG III, RPG IV fijo, mixto y libre; DDS (PF, LF, DSPF, PRTF); CL |
| 2 | Contrato del adaptador: inventario, tipos neutrales, clasificación, slices, `data_of`, ramas de cobertura, digest |
| 3 | Espacio de trabajo ficticio (Cooperativa Andina): un programa por forma de RPG, sus DDS y un CL de cierre |
| 4 | Registro en `ADAPTERS` y prueba de elección del adaptador frente a COBOL y Sybase |

## 2. Fuera de R1

Golden master (R2: conexión a IBM i o trazas, elegido por proyecto), interactivos (R3), quirks de RPG (R4).

## Cómo se valida

Las pruebas del paquete y `test_scope.py` de orquestación; CI con ruff, mypy y la suite completa.
