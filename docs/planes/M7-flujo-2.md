# Plan del hito M7 — Flujo 2: nueva funcionalidad desde documentos, historias y Figma

- **Estado:** en curso (desde 2026-10-01).
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
