# Plan del paso 3b — Caracterización rápida

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0046 (precisión 3b), D-74; medición de la corrida real (25–27 min de Sybase por intento, 87 min colgado).
- **Rama:** `plan-3b-caracterizacion-rapida` (sobre los pasos 6 y 7).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `AseRunner._run_batch`: un isql por lote con marcas por caso; caso cortado se ejecuta solo |
| 2 | Caché de observaciones por huella del caso; sin casos pendientes no arranca el motor |
| 3 | Corte transitorio (`LegacyEngineTimeoutError`) si el motor deja de responder; timeout de `docker` capturado |
| 4 | Pruebas unitarias (lotes, caché, motor mudo) y prueba en vivo con Sybase (`NEXTI_LIVE_ASE=1`) |

Pendiente: mantener el motor encendido entre intentos (hoy un intento con casos nuevos arranca un motor nuevo).
