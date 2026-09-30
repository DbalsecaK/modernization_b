# ADR-0013 — Prototipos React reales, compilados en el sandbox y mostrados en un iframe aislado

- **Estado:** Aceptada · 2026-09-30
- **Secciones:** 7.4, 15 (regla 4: nada generado corre fuera del sandbox), 18.x (Diseño UI), 20 (M5)
- **Relacionadas:** ADR-0010 (sandbox Java), `CLAUDE.md` (código generado solo en el sandbox)

## Contexto

La spec (7.4) pide prototipos navegables en "HTML/React real renderizado en la plataforma", generados por el agente
*UX/UI designer* a partir de las specs de pantalla, y que lo generado se renderice en el sandbox. Un prototipo es
código escrito por un modelo que termina ejecutándose en el navegador de quien lo revisa: no puede tener acceso a la
sesión, a las cookies ni a la API de la plataforma.

## Decisión

- El agente escribe un componente React (TSX) por pantalla, usando **solo** React y el design system NexTI
  (`@nexti/ds`). Un validador por código rechaza cualquier otro import, `fetch`, `eval`, `document.cookie`,
  `window.parent` y URLs externas; el error vuelve al agente (hacer-verificar-corregir).
- El TSX se compila en un **sandbox web** (contenedor sin red, Node + esbuild + React + `@nexti/ds` preinstalados)
  a un bundle estático; se guarda en el object store como una versión del prototipo.
- La web lo muestra en un **iframe con `sandbox="allow-scripts"`** (sin `allow-same-origin`: origen opaco, sin
  cookies ni almacenamiento de la plataforma) y la API lo sirve con **CSP estricta** (`default-src 'none'`, scripts y
  estilos solo del propio bundle, `connect-src 'none'`, `frame-ancestors` de la plataforma). La comunicación con la
  página (clic en un campo para comentar, navegación entre pantallas) es por `postMessage` con un esquema cerrado.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Prototipo declarativo (JSON dibujado por componentes de la plataforma) | Nada generado se ejecuta, pero no es el "React real" que pide la spec ni sirve de base para la generación del frontend |
| Renderizar el TSX en la misma página de la plataforma | El código del modelo tendría la sesión y la API: inaceptable (regla 4) |
| Un subdominio aparte para los prototipos | Aísla igual, pero exige otro origen en el despliegue; el iframe con origen opaco da el mismo aislamiento hoy |

## Consecuencias

- Hay una segunda imagen de sandbox (`nexti-sandbox-web`) que se construye local y en CI.
- El design system NexTI es un paquete React compartido por la web y los prototipos.
- Un prototipo aprobado en C2 es código fuente reutilizable por la generación del frontend (M7+).

## Cómo se valida

- Tests del validador (imports prohibidos, APIs del navegador prohibidas, URLs externas).
- Test de la API: el bundle se sirve con la CSP y sin cookies de sesión; sin permiso no se sirve.
- e2e: el prototipo se ve en el iframe, no puede leer la sesión ni llamar a la API.
