# Plan del hito M27b — Casos por rama y código citado

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0047 (precisión M27b), D-76; plan aprobado (paso 5).
- **Rama:** `m27b-casos-por-rama` (sobre M27a).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `CoveredBranch.file`: el adaptador Sybase registra el fuente de cada rama |
| 2 | Caracterización guiada: una ronda que devuelve las ramas sin caso con su código y las reglas que las citan |
| 3 | Extracción guiada: `rules/citations.json` con el código de cada cita |
| 4 | Tarjeta de regla en C1: cada cita desplegable con el código numerado |
| 5 | Pruebas: ronda de ramas (caracterización), lectura de citas (web), aceptaciones grabadas sin cambios |

## Consecuencias

- Una ronda más del test engineer cuando quedan ramas sin caso (una sola; lo demás se reporta).
- El aprobador ve el código detrás de cada regla en C1.

## Cómo se valida

Prueba de caracterización: con una rama sin caso, la verificación pide los casos que faltan una sola vez y la
segunda grabación cierra. Prueba web de la lectura de citas (válidas, inválidas, ausentes). Aceptación M18 sin cambios.
