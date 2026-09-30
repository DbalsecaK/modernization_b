# Plan del hito M5 — BMS → pantallas y prototipos

- **Estado:** cerrado (2026-09-30), ver la sección 4. Sigue M6 (PR apilada sobre esta rama).
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

**Desviación del paso 9.** La tabla `question` (10.4) exige una corrida y el chat no la tiene. Por eso un cambio
que agrega campos que la spec de pantalla no tiene no genera una pregunta 10.4: queda como **propuesta en el chat**,
con su prototipo ya compilado. Una persona con `prototipo.editar` la acepta (la spec de pantalla gana los campos
como versión nueva y el prototipo propuesto pasa a ser versión nueva) o la rechaza. Un cambio que se mantiene
dentro de la spec produce directamente una versión nueva. El chat nunca aprueba C2.

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Todos los campos de los mapas de la aplicación de referencia aparecen en la spec de pantalla con posición, longitud y atributos correctos | Parser contra la spec de referencia ficticia; e2e de la pestaña |
| El prototipo generado corre aislado: sin sesión, sin API, sin red | Validador, API (CSP) y e2e |
| Cada cambio pedido por chat es una versión nueva; un cambio que toca algo aprobado genera una pregunta; el chat no aprueba C2 | Orquestación, API y e2e |
| Permitido y denegado por endpoint, aislamiento y auditoría | Matriz de autorización y RLS |

## 4. Cierre de M5 (2026-09-30)

Los criterios de la sección 3 se cumplen con tests automatizados. Corren en CI contra los servicios reales, el
sandbox web (`nexti-sandbox-web:1`) y la grabación de la corrida real.

| Criterio | Evidencia (tests) | Estado |
|---|---|---|
| Todos los campos de los mapas de referencia aparecen en la spec de pantalla con posición, longitud y atributos | `test_bms.py`: el parser contra `reference_screens.json`, 3 mapas y 49 campos contando literales. `test_acceptance_m5.py`: los mismos campos, leídos por el worker desde el zip subido y servidos por la API. `e2e/ui-design.spec.ts`: la tabla de campos de la pestaña | ✅ |
| El prototipo corre aislado: sin sesión, sin API, sin red | `test_ui.py`: el validador rechaza red, eval, storage, `window.parent`, navegación, URLs externas y HTML crudo. `test_screens_api.py`: CSP `default-src 'none'`, `connect-src 'none'`, `sandbox allow-scripts` sin `allow-same-origin`, sin cookies. e2e: el iframe con `sandbox="allow-scripts"` y los mensajes del protocolo cerrado (`frameEvent`) | ✅ |
| Cada cambio pedido por chat es una versión nueva; un cambio de spec se propone y lo decide una persona; el chat no aprueba C2 | `test_ui_chat.py` (worker y sandbox real: versión, propuesta, fallo), `test_screens_api.py` (encolado, aceptar y rechazar, auditoría), aceptación grabada (el cambio vuelve como v2), e2e (propuesta aceptada) | ✅ (ver desviación del paso 9) |
| Permitido y denegado por endpoint, aislamiento y auditoría | `test_endpoints_authz.py`: 131 casos, entre ellos las 14 rutas de pantallas, prototipos, comentarios y chat. `test_rls.py` con las tablas nuevas. Modelo OpenFGA 9/9 | ✅ |

**Aceptación grabada.** `test_acceptance_m5.py` se grabó una vez con `anthropic/claude-sonnet-5.5`: 4 llamadas y
0,19 USD, dentro del tope de 5 USD. Pasa esto:

- El worker lee `PAGOSET.bms` del zip y genera 3 specs de pantalla.
- El diseñador UX/UI escribe un prototipo por pantalla que muestra los 16 campos de datos y compila sin correcciones.
- La API sirve cada prototipo con la CSP del iframe.
- El cambio pedido por el chat vuelve del worker como la versión 2.

CI reproduce la grabación sin red.

**Capturas** en `docs/m5/`, generadas por el e2e con `CAPTURE_DIR`:

- la pestaña Diseño UI con el catálogo;
- la pantalla legacy 24×80 con un campo enlazado al prototipo aislado;
- el chat con la propuesta aceptada.

**Cambios respecto del plan**

- Las propuestas de cambio de spec se deciden en el chat, no como preguntas 10.4 (ver la desviación del paso 9).
- Los pasos 10 y 11 se hicieron juntos. La vista legacy ↔ prototipo vive en la misma pestaña: la pantalla terminal
  se dibuja desde la spec y los campos se enlazan en ambos sentidos con los comentarios.
- La API expone `prototype.comment` y `prototype.edit` en los permisos del proyecto para que la web muestre u oculte
  acciones.
- La aceptación destapó que el worker no leía los mapas `.bms` de los zip. Ya los lee.

**Limitaciones conocidas**

- El chat no acepta adjuntos (capturas). El mock los tenía; la API todavía no.
- Un campo agregado al aceptar una propuesta entra como `input` de longitud 40, sin posición. Una persona lo ajusta
  editando la spec de pantalla (versión nueva).
- El iframe solo envía mensajes: la plataforma no puede resaltar un campo dentro del prototipo, solo en la pantalla
  legacy y en la tabla.
- Los mapas reales de BI-cobol no se probaron (fuera del repo por ADR-0011). Se pueden correr a demanda con
  presupuesto explícito.
- La compuerta C2 se aprueba en la corrida (pestaña Corridas). La pestaña Diseño UI solo lleva hasta allí.
- Gasto real en modelos durante M5: 0,19 USD.
