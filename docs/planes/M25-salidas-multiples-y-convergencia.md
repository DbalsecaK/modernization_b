# Plan del hito M25 — Puertos con varias salidas y convergencia persistente

- **Estado:** cerrado (2026-10-06).
- **Fuente:** secciones 6.1, 10.3, 11.1 y 11.3; ADR-0043 y D-62; nota pendiente de ADR-0035 (2026-10-06).
- **Rama:** `m25-salidas-multiples-y-convergencia`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `PortMethod.legacy_outputs` y su validador; `target_case` con `outputs` por respuesta del stub |
| 2 | Arneses Java (Spring JDBC, MongoDB, Quarkus): record desde `outputs` (Optional si procede); `failure` con el primer marco del paquete generado |
| 3 | Guía de diseño guiado (`GUIDED_DESIGN`); regla guiada "un método por puerto que reemplaza un programa" de vuelta en `design_problems` |
| 4 | `Verification.progress`; `do_verify_correct` no cuenta los intentos con progreso (tope `ATTEMPTS_AT_MOST`) |
| 5 | `fidelity.rebuild_base`: la base de la convergencia se reconstruye del journal tras un reinicio |
| 6 | Pruebas: `test_fidelity.py`, `test_generation.py`, `test_equivalence.py` (pack); regresión completa; corrida real desde Architecture |
| 7 | ADR-0043, D-62; nota en ADR-0035 |

## 2. Cierre

Validado con las suites de core, orquestación, packs, API y web. La corrida real se reintenta desde Architecture
(el diseño anterior falló por la regla retirada) y su resultado va en el informe de la corrida.
