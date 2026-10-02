# Plan del hito M13 — Ola 2, segunda parte: Quarkus y Next.js

- **Estado:** cerrado (2026-10-02).
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

## 4. Cierre

**Lo que se entrega**

- **Quarkus** (`nexti_pack_spring_boot.quarkus`, `QUARKUS_PACK`), una subclase del pack Java:
  - dominio, puertos, contratos, esquema, servicios y pruebas idénticos a Spring Boot;
  - bordes propios: recursos JAX-RS (cuerpo JSON en POST/PUT/PATCH, parámetros de consulta en GET/DELETE), adaptadores
    JDBC con `javax.sql.DataSource` inyectado, cableado CDI con productores; `pom.xml` con el BOM de Quarkus 3.40.1;
  - arnés de equivalencia propio con JDBC plano y la misma reflexión sobre el servicio;
  - imagen `nexti-sandbox-java-quarkus:1` (PostgreSQL 17 en loopback, Temurin 21, 139 bibliotecas resueltas en el
    build); prompt `backend-dev-quarkus` para los adaptadores; la skill `quarkus` ajustada al pack (1.1.0).
- **Next.js** (`nexti_pack_frontend.nextjs`):
  - App Router; cada pantalla es un componente cliente que no usa APIs de Next (navega con `navigate()`), así que el
    arnés de pantallas es el de React;
  - el chequeo de tipos usa los tipos reales de Next; las páginas y rutas se empaquetan con *shims* de `next/link` y
    `next/navigation` para probar que todo resuelve, sin `next build`;
  - BFF opcional (`app/api/[...path]/route.ts`) con arquitectura `bff-microservices`: solo reenvía a
    `NEXTI_BACKEND_URL`;
  - imagen `nexti-sandbox-frontend:2` con next 16.3.8, sin el compilador nativo ni sharp (692 MB).
- **Catálogo:** Quarkus y Next.js pasan a certificados; CI, release, Helm y el arranque local construyen las imágenes.

**Evidencia**

- `test_quarkus.py`: el objetivo de referencia en Quarkus compila, sus 7 pruebas pasan y reproduce **12 de 12**
  casos del golden master; un adaptador de Spring no compila ahí; el canario se detecta.
- `test_nextjs.py`: las pantallas de referencia pasan todos los chequeos del arnés y axe, con y sin BFF; una pantalla
  que rompe el contrato o no tipa falla con su motivo. React y Angular siguen pasando con la imagen nueva.
- `test_frontend.py`: generación de punta a punta de Next.js con BFF, con una pantalla rechazada y corregida.

**Queda para después**

- Quarkus con Oracle o MySQL, y el Flujo 3 sobre aplicaciones Quarkus.
- Límite transaccional y mapeo de errores de negocio a HTTP en los bordes (igual que en Spring Boot hoy).
- Aceptaciones con modelos reales sobre Quarkus y Next.js (necesitan grabación).
