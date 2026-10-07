# Plan de la precisión P31 — Las pruebas se compilan antes del servicio

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0042 (precisión P31), D-64; corrida 44027f4f tras ADR-0044: tres intentos del desarrollador
  fallaron con el mismo error de compilación en el archivo de pruebas (`cannot find symbol` en el helper `Req`).
- **Rama:** `p31-pruebas-compiladas-antes-del-servicio`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `generate.placeholder_service` y `SpringBootPack.placeholder_service` (las tres variantes Java lo heredan) |
| 2 | `GenerationPhases._tests`: en modo guiado, `do_verify_correct` con verificación por compilación (sandbox + relleno); no guiado sin cambios |
| 3 | Prueba en `test_fidelity.py`; ADR-0042 (nota P31), D-64 |

## 2. Cierre

Validado con las suites de orquestación y del pack; la corrida real se reintenta desde Generation.
