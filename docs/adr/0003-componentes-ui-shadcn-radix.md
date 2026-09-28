# ADR-0003 — Componentes UI con shadcn/ui sobre Radix (D-14)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 18.5, 18.7, 19.2, M0

## Contexto

El prototipo de `apps/web` usa Tailwind 4 con tokens propios (claro y oscuro) y primitivas hechas a mano en
`components/ui/primitives.tsx` y `components/ui/overlay.tsx` (Button, Select, Tabs, Drawer, Toast, etc.). La
especificación exige WCAG 2.1 AA; los diálogos, menús, combobox y tooltips accesibles (foco, teclado, ARIA)
son la parte más difícil de hacer bien a mano.

## Decisión

Adoptar **shadcn/ui** (componentes de **Radix** copiados al repositorio y estilizados con Tailwind) **detrás
de las primitivas existentes**, sin cambiar su API:

- Primero: `Drawer` → Dialog/Sheet, `Select`, Combobox (grafo y human in the loop), `Tooltip`, `Toast`, `Tabs`.
- Los estilos usan los tokens actuales; las pantallas siguen importando los mismos componentes y no se tocan.
- Se valida con tests de accesibilidad (axe) en Playwright.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| MUI, Ant Design, Mantine | Traen su propio sistema de estilos, que choca con Tailwind y los tokens; más peso y más difícil de adaptar a la marca de cada cliente |
| Seguir con primitivas propias | Posible, pero la accesibilidad de overlays y combobox sería trabajo propio permanente |
| Headless UI | Menos componentes que Radix (sin combobox con la misma cobertura, menús anidados, tooltips) |

## Consecuencias

- El código de los componentes vive en el repo (se actualiza a mano, sin dependencia de versión de una librería de UI).
- Radix se agrega como dependencia (versiones fijadas).

## Cómo se valida (M0)

Las primitivas migradas pasan los tests de axe y los tests existentes (`pnpm web:test`); ninguna pantalla cambia su import.
