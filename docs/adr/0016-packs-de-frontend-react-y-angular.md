# ADR-0016 — Packs de frontend React y Angular: contrato OpenAPI, cliente tipado y arnés de pantallas

- **Estado:** Aceptada · 2026-09-30
- **Secciones:** 8.4 (packs de destino), 7.4 (prototipos), 11.3 (verificación), 20 (M6b)
- **Relacionadas:** ADR-0010 (pack Java Spring Boot), ADR-0013 (prototipos React), ADR-0014 (hitos de packs)

## Contexto

M6b agrega los frontends React y Angular. Deben usar el design system aprobado en C2 y un cliente tipado del
backend, generar las pantallas desde sus specs y prototipos, y probarse en el sandbox. El contrato del backend
hoy solo existe como código Java generado, y la imagen web de M5 solo compila prototipos aislados: no tiene
TypeScript, jsdom, axe ni Angular.

## Decisión

- **Contrato OpenAPI desde el diseño.** El diseño aprobado en C3 ya dice, por cada caso de uso, su método, su
  ruta, sus entradas y salidas con tipos neutrales y sus errores de negocio. Un módulo de código (`nexti_frontend`)
  lo convierte en un documento OpenAPI 3.1. De ese documento sale, también por código, el cliente tipado
  TypeScript que usan los dos packs. No hay un paso de modelo en el contrato.
- **Una imagen de sandbox de frontend** (`nexti-sandbox-frontend`), sin red al ejecutar, con versiones fijadas:
  - TypeScript 6.0, esbuild y React 19;
  - Angular 22 con su compilador AOT (`ngc`, plantillas estrictas);
  - jsdom y axe-core.
- **Compilar es pasar el chequeo de tipos:** `tsc --noEmit` estricto en React y `ngc` en Angular, antes de empaquetar.
- **Arnés de pantallas escrito por la plataforma.** Monta cada pantalla generada en jsdom y verifica contra su spec:
  - cada campo tiene `data-field` y una etiqueta accesible;
  - los obligatorios avisan al enviar vacío;
  - las longitudes máximas y los numéricos se respetan;
  - cada acción de la spec está presente y la principal llama al cliente;
  - la navegación usa las pantallas de la spec;
  - axe-core no encuentra violaciones graves ni críticas.

  Las reglas visuales que jsdom no puede medir (contraste) quedan fuera y se dicen.
- **El agente escribe solo las pantallas.** El esqueleto (shell, router, cliente, design system) es determinista.
  El agente *frontend-dev* escribe cada pantalla desde su spec, su prototipo y el cliente, y el arnés la verifica
  (hacer-verificar-corregir).
- **Design system en cada pack.** React usa los componentes de `@nexti/ds`. Angular usa las mismas clases CSS y
  los mismos tokens del design system (`ds.css`), con plantillas propias.
- **Veredicto propio.** La verificación calcula un veredicto del frontend con sus chequeos: compila, arnés,
  cobertura de las specs y accesibilidad. No se mezcla con el veredicto de equivalencia del backend.
- **Sin pack, espera (D-06).** Un frontend sin pack (por ejemplo Next.js) deja la generación esperando; con
  `none` no se genera frontend.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Que el agente escriba también el cliente HTTP | El contrato se deriva del diseño; escribirlo con un modelo agrega errores evitables |
| Playwright con Chromium en el sandbox | Imagen mucho más pesada y lenta; jsdom con axe cubre campos, validaciones, acciones y la mayoría de reglas WCAG |
| Angular Material para el pack Angular | Otro design system distinto del aprobado en C2; se usan las clases y tokens NexTI |
| Un veredicto único backend + frontend | Mezcla evidencias distintas; un fallo de accesibilidad no dice nada de la equivalencia del backend |

## Consecuencias

- Hay una tercera imagen de sandbox que se construye local y en CI.
- El worker lee las specs de pantalla, los prototipos y el design system para el paso de frontend.
- El contrato OpenAPI queda como artefacto del proyecto y sirve también a quien consuma el backend.

## Cómo se valida

- Tests del generador de OpenAPI y del cliente (deterministas).
- Tests de cada pack con pantallas de referencia escritas a mano: compilan y pasan el arnés; una pantalla con un
  campo faltante, una validación ausente o una violación de axe falla con el motivo.
- Aceptación grabada: la aplicación ficticia genera frontend React y Angular que compilan y pasan el arnés.
