# Plan R3 — Programas RPG interactivos

- **Estado:** cerrado (2026-10-08).
- **Fuente:** ADR-0054, D-87; plan de soporte RPG aprobado.
- **Rama:** `r3-pantallas-5250` (sobre R4).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `nexti_adapter_rpg.screens`: registro de DSPF a `ScreenSpec` (campos, literales, teclas, tamaño, reglas) |
| 2 | `RpgAdapter.screens` y `screens_of` de la fase de UI |
| 3 | Trazas ficticias de sesión 5250 de `CONSCTA` como golden master |
| 4 | El runner en vivo de IBM i rechaza los programas interactivos con el motivo |

## 2. Pendiente

Emulación 5250 en vivo (PROVEN para interactivos) y semántica de subarchivos.

## Cómo se valida

Pruebas de pantallas, de la fase de UI y del golden master interactivo.
