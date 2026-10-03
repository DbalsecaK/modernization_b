# Plan del hito M11 — Flujo 3: añadir funcionalidad a una aplicación existente

- **Estado:** cerrado (2026-10-02); aceptación grabada el 2026-10-03 con el OK del aprobador.
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

## 4. Cierre

**Lo que se entrega**

- **Flujo `extendExisting`** en el catálogo (C1, C3 y C4), la composición, la base (migración 0017), la API, el
  worker y la web. La aplicación existente entra como `source_archive` (opción de fuente `spring-boot-app`) y el
  pedido como documentos. functional-analyst (0.10.0) se recomienda también para el Flujo 3.
- **Orquestación (`nexti_orchestration.extension`):**
  - inventario AS-IS por código (el de `nexti_ivv.target`) y **línea base**: la aplicación compilada con sus propias
    pruebas en el sandbox del pack;
  - **diseño del delta** propuesto por el arquitecto y validado por código: historias cubiertas, sin choques con
    endpoints existentes, reutilizaciones y tablas que existen, sin tocar pruebas ni el archivo de build;
  - **generación del delta:** pruebas de aceptación por criterio y código nuevo o archivos existentes completos,
    verificados con todas las pruebas de la aplicación (hacer → verificar → corregir);
  - **validación por código** con `EXTEND_CHECKS` (`regression`, `criteria_covered`, `contract_kept`, `fitness`,
    `canary`, `traced_to_inputs`), paquete de prueba y `delta/DELTA.md`;
  - entrega del delta solo, con su índice de archivos nuevos y cambiados.
- **API:** `GET /projects/{id}/delta` (`code.view`): inventario AS-IS, línea base, diseño, archivos e informe.
- **Web:** cuarta tarjeta del asistente, insumos del flujo, pestaña Delta y los checks del Flujo 3 (en/es).

**Evidencia**

- **`test_extension.py`:** BillPay como aplicación existente (5 pruebas propias) recibe la consulta del estado de una
  orden con modelos guionados: el diseño se corrige una vez (historia desconocida), el código una vez (prueba en
  rojo), y el veredicto es **PROVEN** con los seis chequeos.
- **Pruebas puras:** el diseño contra el inventario, la ubicación de los archivos, las fitness functions y el
  contrato AS-IS (un endpoint quitado se detecta).
- **API:** matriz de permisos, aislamiento entre tenants y estado vacío antes del inventario.
- **`test_acceptance_m11.py`** (grabada el 2026-10-03 con modelos reales): BillPay recibe la consulta del estado de una
  orden y el veredicto es **PROVEN** con los seis chequeos. Las 5 pruebas de la línea base siguen pasando, los 4
  criterios del pedido tienen su prueba en verde, el endpoint existente se mantiene y el canario lo detecta una prueba
  nueva. Fueron 5 llamadas por **0,14 USD reales** (de un tope de 2 USD); el CI la reproduce sin costo.

**Cambios respecto del plan**

- El canario del pack muta cálculos; el código de un delta suele ser consultas y guardas. El Flujo 3 agrega
  mutaciones de respaldo (condición de vacío negada, igualdad invertida) solo cuando el pack no encuentra qué cambiar.
- No hubo que tocar las versiones de solution-architect, backend-dev ni test-engineer: ya se recomiendan para todos los
  flujos.

**Queda para después**

- Delta de UI y pilas distintas de Spring Boot.
