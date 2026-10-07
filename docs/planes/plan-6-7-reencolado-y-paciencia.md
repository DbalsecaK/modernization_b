# Plan de los pasos 6 y 7 — Reencolado y paciencia ante fallos transitorios

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0046, D-73; plan aprobado tras la corrida PROVEN (pasos 6 y 7).
- **Rama:** `plan-6-7-reencolado-y-paciencia`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `LegacyUnavailableError.transient`, `LegacyEngineTimeoutError`; reintento en la caracterización (60 s, 180 s) |
| 2 | `:retry` sobre una corrida en espera por fase no disponible: reencolar sin reiniciar |
| 3 | Pasarela: rondas pacientes (30 s, 60 s, 2 min, 4 min) cuando toda la cadena falla por causas transitorias |
| 4 | Pruebas de caracterización, pasarela y API; ADR-0046, D-73 |
