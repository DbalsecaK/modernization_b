# Plan del hito M13 — Ola 2, segunda parte: Quarkus y Next.js

- **Estado:** en curso (desde 2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 8.4, 8.5, 8.7 y 20 (Posterior);
  - ADR-0028 y D-47.
- **Rama:** `m13-ola2-quarkus-nextjs`, encima de `m12-ola2-datos-nube`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0028. El aprobador pidió avanzar de corrido hasta terminar.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Quarkus como framework del pack Java (bordes JAX-RS, JDBC con DataSource, CDI) | Compilación nativa (GraalVM) |
| Imagen `nexti-sandbox-java-quarkus` y golden master del objetivo de referencia | Quarkus con Oracle o MySQL |
| Next.js como sabor del pack de frontend, con BFF opcional | `next build` dentro del sandbox |
| Catálogo, CI, release y Helm | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0028 y D-47 |
| 2 | Quarkus: pack, imagen, objetivo de referencia y golden master |
| 3 | Next.js: plantillas, sabor del pack, imagen `nexti-sandbox-frontend:2` y arnés de pantallas |
| 4 | Catálogo, composición, CI, release y Helm |
| 5 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El esqueleto Quarkus compila con el núcleo del diseño | Pruebas del pack Quarkus |
| El objetivo de referencia en Quarkus reproduce el golden master en el sandbox | Pruebas del pack Quarkus |
| Las pantallas de referencia en Next.js pasan el arnés y axe | Pruebas del pack de frontend |
