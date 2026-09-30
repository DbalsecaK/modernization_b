# Plan del hito M6b — Packs de frontend: React y Angular

- **Estado:** en ejecución (2026-09-30). Se avanza de corrido. Al terminar sigue M6c (PR apilada sobre esta rama).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 8.4 (packs de destino), 7.4 (prototipos), 11.3
  (verificación), 20 (M6b); ADR-0013 (prototipos) y ADR-0014 (hitos de packs).
- **Rama:** `m6b-packs-frontend`, apilada sobre `m6-cobol-cics`. Un commit por paso y PR al terminar.
- **Decisiones del aprobador (2026-09-30):** grabaciones con modelos reales dentro de los 10 USD de M6, M6b y M6c
  (quedan 7,05), con aviso antes de cada una.

## 1. Alcance

| Incluye | No incluye (hitos posteriores) |
|---|---|
| Contrato del backend como OpenAPI 3.1, derivado por código del diseño aprobado en C3 | Next.js (Ola 2) |
| Cliente tipado TypeScript generado del OpenAPI (determinista), el mismo para React y Angular | Pruebas en navegadores reales (Chromium): se prueban en jsdom |
| Pack React: esqueleto (shell, router, cliente, `@nexti/ds`) y una página por pantalla | Temas de marca del cliente distintos de la base NexTI |
| Pack Angular: esqueleto (standalone, router, cliente, clases del design system) y un componente por pantalla | |
| Imagen `nexti-sandbox-frontend` sin red: TypeScript, esbuild, React, Angular (compilador AOT), jsdom y axe-core | |
| Arnés de pantallas escrito por la plataforma: campos, etiquetas, validaciones, acciones, navegación y axe | |
| El agente *frontend-dev* escribe cada pantalla desde su spec, su prototipo y el cliente (hacer-verificar-corregir) | |
| Paso de frontend en la generación; sin pack el paso espera (D-06); veredicto propio del frontend | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan y ADR-0016 |
| 2 | `nexti_frontend`: OpenAPI desde el diseño, cliente tipado y contrato de pantalla (campos, validaciones, acciones) |
| 3 | Imagen `nexti-sandbox-frontend` y arnés de pantallas en jsdom con axe |
| 4 | Pack React: esqueleto, compilación con `tsc` y esbuild, arnés |
| 5 | Pack Angular: esqueleto, compilación AOT con `ngc`, arnés |
| 6 | Orquestación: paso de frontend en la generación, lecturas del worker, veredicto del frontend |
| 7 | Aceptación con la aplicación ficticia (SP de M4 + mapas de M5), grabada con aviso previo |
| 8 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El frontend React y el Angular compilan | Build en el sandbox (`tsc --noEmit`, `ngc`) en los tests de cada pack y en la aceptación |
| Pasan sus tests | Arnés de pantallas en jsdom (por pantalla) |
| Cubren todos los campos, validaciones y acciones de las specs de pantalla | Arnés: cada campo con `data-field` y etiqueta accesible, obligatorios y longitudes, cada acción |
| axe sin violaciones graves | axe-core en jsdom dentro del arnés |
| Sin pack, la generación del frontend espera | Test de orquestación (frontend sin pack) |
