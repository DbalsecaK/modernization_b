# Plan del hito M5 — BMS → pantallas y prototipos

- **Estado:** en ejecución (2026-09-30). Se avanza de corrido; solo se detiene ante una decisión importante. Al
  terminar sigue M6 (PR apilada sobre esta rama).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 4.1 (Pantalla), 7.4, 8.3 (Mapas BMS), 18 (Diseño UI),
  20 (M5).
- **Rama:** `m5-bms-pantallas`, un commit por paso, PR a `main` al terminar.
- **Foco del aprobador:** terminar la aplicación (frontend, backend e integraciones). Las corridas contra kits de
  clientes quedan fuera de este hito.
- **Decisiones del aprobador (2026-09-30):**
  - **Referencia:** una aplicación BMS ficticia escrita para el repo (CI). Los mapas reales de BI-cobol no entran al
    repo (ADR-0011) y no se usan en M5.
  - **Prototipos:** React real, compilado en el sandbox y mostrado en un iframe aislado (ADR-0013).
  - **Modelos:** respuestas grabadas en el CI; la grabación con modelos reales tiene un tope de 5 USD y se avisa antes
    de cada grabación.

## 1. Alcance

| Incluye | No incluye (hitos posteriores) |
|---|---|
| Spec de pantalla (4.1) con campos (posición, longitud, atributos, tipo, validación, mensaje), acciones, estados y navegación | COBOL/CICS y Transacción → Programa → Mapa (M6) |
| Adaptador BMS determinista (`DFHMSD/DFHMDI/DFHMDF`) → spec de pantalla | ASPX (M8) |
| Design system base NexTI (tokens y componentes) y su catálogo | Exportar a Figma |
| Prototipos React por pantalla, compilados en el sandbox, versionados; comentarios; C2 | Lectura de Figma por API (M7) |
| Chat de cambios al prototipo con versiones y preguntas (D-24) | Generación del frontend desde los prototipos (M7+) |
| Pestaña Diseño UI conectada y vista legacy ↔ prototipo | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan y ADR-0013 |
| 2 | `nexti_core.spec.screens`: modelo de la spec de pantalla y su validación |
| 3 | `packages/adapters/source/bms`: parser determinista → spec de pantalla; aplicación BMS ficticia y su spec de referencia |
| 4 | Migración 0010: specs de pantalla, design system, prototipos versionados, comentarios y chat (RLS, permisos) |
| 5 | Design system base NexTI (`@nexti/ds`): tokens y componentes, usado por la web y los prototipos |
| 6 | Sandbox web (`nexti-sandbox-web`) y validación y compilación del TSX del prototipo |
| 7 | Fase UI del pipeline: el diseñador UX/UI genera y verifica un prototipo por pantalla; C2 |
| 8 | API: specs de pantalla, prototipos servidos con CSP, versiones y comentarios |
| 9 | Chat de cambios (D-24): job del worker que produce una versión nueva o una pregunta |
| 10 | Web: pestaña Diseño UI (catálogo, prototipos, versiones, comentarios, chat, referencias) |
| 11 | Web: vista legacy ↔ prototipo (mapa 24×80 junto al prototipo, campos enlazados) |
| 12 | Aceptación de punta a punta con la aplicación ficticia (grabada) |
| 13 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Todos los campos de los mapas de la aplicación de referencia aparecen en la spec de pantalla con posición, longitud y atributos correctos | Parser contra la spec de referencia ficticia; e2e de la pestaña |
| El prototipo generado corre aislado: sin sesión, sin API, sin red | Validador, API (CSP) y e2e |
| Cada cambio pedido por chat es una versión nueva; un cambio que toca algo aprobado genera una pregunta; el chat no aprueba C2 | Orquestación, API y e2e |
| Permitido y denegado por endpoint, aislamiento y auditoría | Matriz de autorización y RLS |
