# Plan del hito M20 — Versiones por eje

- **Estado:** cerrado (2026-10-05).
- **Fuente:** secciones 8.3, 8.4 y 8.6; ADR-0037 y D-56.
- **Rama:** `m20-versiones-por-eje`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Catálogo: `versions` por opción de destino y de origen, con nivel y predeterminada; modelo `Version`, carga y validación en el motor de composición (`unknown_target_version`, `target_version_not_available`) |
| 2 | API: `target.versions` al crear y al leer el proyecto; el catálogo expone las versiones; el worker las pasa planas a la corrida |
| 3 | Web: selector de versión bajo cada eje (las planificadas deshabilitadas), versiones del adaptador junto al origen, versiones en la pestaña de packs del catálogo |
| 4 | Pruebas de composición y de API; ADR-0037 y D-56 |

## 2. Cierre

Versiones certificadas hoy: Spring Boot 3.5, Quarkus 3.40, .NET 10, Go 1.26, Next.js 16, React 19, Angular 22,
Sybase ASE 16.0 (origen). Planificadas: Spring Boot 3.4, React 18, Angular 21, ASE 15.7. Lo que falta para cada
planificada queda escrito en el ADR.
