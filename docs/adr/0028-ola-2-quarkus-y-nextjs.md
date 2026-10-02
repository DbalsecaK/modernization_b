# ADR-0028 — Ola 2 (segunda parte): Quarkus y Next.js

- **Estado:** Aceptada · 2026-10-02
- **Secciones:** 8.4 (packs de destino), 8.5 (matriz de compatibilidad), 8.7 (olas de certificación), 20 (Posterior)
- **Relacionadas:** ADR-0010 (pack Spring Boot), ADR-0016 (packs de frontend), ADR-0017 (contrato de packs),
  ADR-0027 (ola 2, primera parte)

## Contexto

La matriz de compatibilidad (8.5) dice:

- Quarkus y Spring Boot comparten el núcleo Java: un pack con adaptadores de framework distintos;
- Next.js puede ser frontend o frontend + BFF, y eso cambia qué se genera en el backend.

El pack Spring Boot ya tiene un núcleo hexagonal sin framework (dominio, puertos, casos de uso, servicios de
aplicación) y el framework solo en los bordes (controladores REST, adaptadores JDBC, cableado). El pack de frontend
ya tiene React y Angular con el mismo contrato OpenAPI, el mismo arnés de pantallas y el mismo veredicto.

## Decisión

- **Quarkus como segundo framework del pack Java.**
  - El dominio, los puertos, los casos de uso y los servicios de aplicación se generan igual que en Spring Boot: el
    agente escribe el mismo código, y las pruebas del oráculo y el golden master son los mismos.
  - Cambian los bordes: recursos JAX-RS (`jakarta.ws.rs`), adaptadores JDBC con `javax.sql.DataSource` (Agroal) y
    cableado CDI (`@ApplicationScoped`, productores) en lugar de los beans de Spring.
  - **Imagen `nexti-sandbox-java-quarkus`:** las bibliotecas de Quarkus resueltas en el build de la imagen, con
    PostgreSQL en loopback como en `nexti-sandbox-java`. La compilación y las pruebas usan javac y JUnit como en
    Spring Boot. El arnés de equivalencia llama al servicio de aplicación por reflexión, así que no depende del
    framework.
  - Se elige con `backend: quarkus` en el destino.
- **Next.js como tercer sabor del pack de frontend.**
  - Usa el App Router con componentes cliente para las pantallas, el mismo cliente tipado del contrato OpenAPI y el
    mismo arnés de pantallas en jsdom con axe.
  - La imagen de frontend suma `next` y pasa a `nexti-sandbox-frontend:2`. La verificación chequea tipos y arma las
    pantallas con esbuild como en React, sin `next build` en el sandbox (sin red, `/work` sin ejecución).
  - **Frontend + BFF:** la ruta `app/api/[...path]/route.ts` reenvía al backend generado. El backend es el de
    siempre; el BFF no lleva lógica de negocio.
  - Se elige con `frontend: nextjs`.

## Consecuencias

- **Un mismo diseño (C3) sale en Spring Boot o en Quarkus.** El veredicto mide lo mismo en los dos.
- **Next.js comparte el contrato y el arnés con React.** Si el día de mañana se usa `next build`, cambia la
  verificación de la imagen, no las pantallas.
- **Las aceptaciones con modelos nuevos necesitan grabación aparte.** Las pruebas de este hito usan objetivos de
  referencia escritos a mano.
