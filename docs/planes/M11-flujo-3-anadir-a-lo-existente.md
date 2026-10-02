# Plan del hito M11 — Flujo 3: añadir funcionalidad a una aplicación existente

- **Estado:** en curso (desde 2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 3.1 y 3.3, 7, 11.4 y 20 (Posterior);
  - ADR-0026 y D-45.
- **Rama:** `m11-flujo-3`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0026. El aprobador pidió avanzar de corrido hasta terminar.
- **Presupuesto de grabación:** hasta 2 USD, a confirmar antes de grabar.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Flujo `extendExisting` en catálogo, composición, proyectos, API y web | Delta de UI (pantallas) |
| Inventario AS-IS por código y línea base de las pruebas existentes | Pilas distintas de Spring Boot |
| Historias del pedido con la mitad documental del Flujo 2 (C1) | |
| Diseño del delta validado contra el inventario (C3) | |
| Generación solo del delta, con todas las pruebas en el sandbox | |
| Veredicto `EXTEND_CHECKS`, informe del delta y entrega por rama o ZIP | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0026 y D-45 |
| 2 | El flujo en el catálogo, la composición, la base (migración), la API y la web |
| 3 | Inventario AS-IS y línea base en el sandbox |
| 4 | Diseño del delta y su validación por código |
| 5 | Generación del delta (pruebas y código) con verificación en el sandbox |
| 6 | Validación `EXTEND_CHECKS`, informe y entrega |
| 7 | Web: delta, línea base y veredicto (en/es) |
| 8 | Aceptación grabada, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| La línea base distingue las pruebas que pasan de las que fallan | Pruebas de la línea base |
| Un diseño que choca con el inventario o deja criterios afuera vuelve con problemas | Pruebas del diseño del delta |
| Un delta que rompe una prueba existente, borra un archivo o cambia un endpoint AS-IS no pasa | Pruebas de la validación |
| La aplicación ficticia recibe una funcionalidad nueva con su veredicto | `test_acceptance_m11.py` |
