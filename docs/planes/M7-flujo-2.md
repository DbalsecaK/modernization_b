# Plan del hito M7 — Flujo 2: nueva funcionalidad desde documentos, historias y Figma

- **Estado:** cerrado (2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 7.1 a 7.5 (Flujo 2), 7.7 (historias y plan), 11.4 (validación) y 20 (M7);
  - ADR-0018.
- **Rama:** `m7-flujo-2`. Un commit por paso y PR al terminar.
- **Decisiones (opción recomendada, 2026-10-01; el aprobador pidió avanzar sin preguntas y que todo quede funcional e
  integrado):**
  - **Ejemplo ficticio:** «Simulador de crédito». Trae requisitos en Markdown, historias con Gherkin en un documento
    y un archivo de Figma grabado.
  - **Presupuesto de grabación:** hasta 5 USD para M7, dentro de los 10 USD propuestos para M7 y M7b.
  - **Documentos.** Markdown y texto se leen en el worker. PDF, Word y Excel se convierten a texto dentro del
    sandbox, porque son insumo no confiable (regla 5).
    - Word y Excel se convierten con la biblioteca estándar de Python, porque son ZIP con XML.
    - PDF se convierte con `pypdf` en la imagen `nexti-sandbox-docs`.
  - **Figma.** Se lee con la API REST de lectura y el token del tenant guardado en OpenBao (Administración →
    Integraciones). Las pruebas y la demo usan la respuesta grabada de un archivo ficticio.
  - **Referencias citables.** Cada insumo se convierte en un texto con líneas: el documento como texto y Figma como
    un árbol de nodos, una línea por nodo. Reglas, historias y pantallas citan `archivo:línea` como en el Flujo 1, así
    la trazabilidad y su verificación no cambian.
  - **Capturas.** Se listan como insumo y la pantalla puede citarlas. Leerlas con visión queda para M7b, porque el
    gateway todavía solo manda texto.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Ingesta de documentos (MD, TXT, PDF, DOCX, XLSX), Figma (API) y links, con versión y hash | Jira y Azure DevOps (M7b) |
| Normalización por agente a capacidades, reglas, historias con Gherkin y pantallas, validada por código | Visión sobre capturas (M7b) |
| Consolidación: huecos deterministas (7.3) y contradicciones (agente) → preguntas con respuesta recomendada | Exportar a Figma |
| Revisión de spec (C1) con el plan por olas; UI (C2) con los prototipos de M5 | Fidelidad visual píxel a píxel contra Figma |
| Diseño con contratos primero (C3) sin legado; generación con los packs existentes | |
| Validación del Flujo 2 (C4): veredicto calculado por código | |
| Integraciones del tenant en Administración (Figma; la misma tabla sirve a Jira/ADO en M7b) | |
| Entrega: el código queda listo para descargar | |
| Aceptación grabada con el ejemplo ficticio de punta a punta | |

**Veredicto del Flujo 2 (11.4, 7.5).** Lo calcula el código con 6 chequeos:

| Chequeo | Pasa cuando |
|---|---|
| Tests | Un build limpio corrió los tests (JUnit XML) y ninguno falló |
| Criterios cubiertos | Cada criterio Gherkin de cada historia activa tiene un test con su id que pasó |
| Contratos | Cada operación del OpenAPI derivado del diseño tiene su endpoint en el código generado |
| Canario | Un cambio deliberado de una línea pone un test en rojo |
| Preguntas cerradas | No quedan preguntas abiertas en el proyecto |
| Trazado a insumos | Cada regla, pantalla e historia cita un insumo aceptado, y la cita existe |

El frontend tiene su propio veredicto, igual que en M6b (ADR-0016).

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0018 y D-37 |
| 2 | Lectores de insumos: documentos (worker y sandbox), Figma como árbol citable, imagen `nexti-sandbox-docs` |
| 3 | Integraciones del tenant: tabla, API con OpenFGA y auditoría, token en OpenBao, pantalla de Administración |
| 4 | Ejecutores de ingesta, normalización y consolidación |
| 5 | Revisión de spec, UI, diseño sin legado, generación con criterios, validación y entrega |
| 6 | Pantallas: Flujo 2 en el resumen del proyecto, insumos de Figma y veredicto del Flujo 2 en Validación |
| 7 | Aceptación grabada «Simulador de crédito» y demo local |
| 8 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Cada lector convierte su insumo en líneas citables | Pruebas de los lectores (DOCX, XLSX y PDF en el sandbox, Figma grabado) |
| Una integración de Figma es del tenant: otro tenant no la ve ni la usa, y cada cambio queda auditado | Pruebas de API con OpenFGA y aislamiento |
| La normalización rechaza citas inexistentes, Gherkin inválido y elementos sin historia | Pruebas unitarias con respuestas fijas |
| Cada hueco de 7.3 detectado produce una pregunta con respuesta recomendada, que se aplica al responderla | Pruebas unitarias de la consolidación |
| Con HU + Figma de ejemplo se genera y valida una funcionalidad de punta a punta, trazada a sus insumos | `test_acceptance_m7.py`, grabada |

## 4. Cierre

**Aceptación grabada.** `test_acceptance_m7.py` corre el Flujo 2 completo por el worker y la API con el ejemplo
«Simulador de crédito»: requisitos e historias en Markdown y un archivo de Figma grabado.

- La ingesta deja 2 documentos y el árbol de Figma como texto citable.
- La normalización produce 6 reglas, 2 pantallas, 2 historias con 6 criterios Gherkin y una capacidad, todo con sus
  citas.
- La consolidación detecta 2 huecos y los convierte en preguntas con respuesta recomendada:
  - la pantalla Simulador no tiene estado vacío;
  - el botón «Descargar PDF» de Figma no navega a ningún lado.
- Se aprueban C1, C2, C3 y C4. Spring Boot genera el backend y React las dos páginas.
- Veredicto del Flujo 2: **PROVEN** con los 6 chequeos.
  - Corrieron 20 tests en un build limpio.
  - Los 6 criterios de aceptación tienen un test que pasó.
  - La única operación del contrato tiene su endpoint.
  - El canario cambió el monto mínimo y el test del límite inferior se puso en rojo.
  - No quedaron preguntas abiertas.
  - Los 10 elementos están trazados a las líneas de sus insumos.
- Veredicto del frontend: **PROVEN** con los 6 chequeos.

La corrida final hace 12 llamadas por 0,46 USD. Con los intentos fallidos, el gasto real de M7 fue de unos 0,8 USD,
de los 5 USD asignados.

**Lo que destaparon las grabaciones**

- **Un test engineer que calcula sus propios valores esperados.** Escribió un total de 6030,00 donde el correcto era
  5790,00, y el developer no podía hacerlo pasar sin romper el comportamiento correcto. En el Flujo 2, el pedido ahora
  dice que los valores esperados salen solo de los criterios y de los escenarios.
- **El contrato de las pantallas web.**
  - El primer botón de una pantalla web llama al backend, así que es el envío del formulario y no una navegación que
    el arnés pruebe con los campos obligatorios vacíos.
  - Los campos numéricos se reconocen por su tipo neutral. Las pantallas de terminal (BMS) conservan su contrato, así
    que las grabaciones de M6b siguen valiendo.

**Cambios respecto del plan**

- El paso 7 se hizo antes que el 6: la aceptación mostró qué pantallas había que ajustar.
- Las historias del Flujo 2 no traen dependencias automáticas: las personas las agregan en el plan (7.7).
- La trazabilidad de Validación también muestra las líneas citadas de documentos y de Figma.

**Limitaciones conocidas**

- Las capturas se listan como insumo, pero todavía no se leen con visión (M7b).
- La fidelidad visual contra Figma no se mide píxel a píxel.
- Los criterios se prueban con los tests del servicio, no de punta a punta contra la aplicación levantada.
- La entrega deja el código para descargar. El push al repositorio del cliente llega con el hito de entrega.
