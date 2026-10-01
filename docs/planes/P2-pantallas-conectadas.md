# Plan P2 — Pantallas conectadas: cero maquetas con backend existente

- **Estado:** cerrado (2026-10-01), ver la sección 4. Sigue P1 (arranque local y guía de prueba).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 18.1 a 18.5 (mapa de la aplicación), 13.5 (vistas de
  consumo) y 18.7 (prototipo navegable: se reemplazan los mocks por la API real sin reescribir las pantallas).
- **Rama:** `p2-pantallas-conectadas`, sobre `main`. Un commit por paso y PR al terminar.
- **Decisión del aprobador (2026-09-30):** P2 va antes que P1 (arranque local y guía de prueba). P2 conecta todas las
  pantallas cuyo backend ya existe; las demás se conectan dentro de su hito.
- No cambia la especificación: cada pantalla ya está descrita en la sección 18. No hay ADR.

## 1. Alcance

| Incluye | No incluye (se conecta en su hito) |
|---|---|
| Contador de *Mis tareas* en el menú | Pestaña Backlog e integraciones Jira/Azure DevOps (M7b) |
| Pestaña **Código**: navegador de archivos generados y descarga en zip, según permisos | Integración Figma (M7) |
| Pestaña **Arquitectura**: bounded context, casos de uso, OpenAPI, ADR del diseño y chequeos del veredicto | Push a Git: es la fase *Entrega* del pipeline (13), no una acción de la pantalla |
| Especificación: subvistas **pantallas** y **contratos** | Administración: autenticación, MFA y proveedores de identidad (M0b) |
| Pestaña **Costos**: por fase, agente y modelo, contra el presupuesto del proyecto | Administración: seguridad e integraciones del tenant (M0b, M7, M7b) |
| **Dashboard** por perfil (ejecutivo, delivery, administrador) con datos reales | Versiones por instancia desplegada (M9) |
| Barra superior: **buscador global** y **notificaciones** | |
| **Operación de plataforma**: workers, colas, ejecuciones en sandbox y errores | |
| Limpieza: se borran los componentes del prototipo que ya no usa ninguna pantalla | |

## 2. Pasos y commits

| # | Paso | API nueva | Permiso |
|---|---|---|---|
| 1 | Plan; contador de tareas real; borrar el código muerto del prototipo (`SpecTabs`, `QualityTabs`, `stories/` de mocks, `decisions/store` y `DecisionCard`) | — | — |
| 2 | Pestaña Código | `GET /projects/{id}/code` (árbol), `GET /projects/{id}/code/file?path=`, `GET /projects/{id}/code:download` (zip, auditado) | `code.view`, `code.download` |
| 3 | Pestaña Arquitectura y subvista Contratos | `GET /projects/{id}/design`, `GET /projects/{id}/contracts` (OpenAPI generado y filas por operación) | `project.view` |
| 4 | Subvista Pantallas de la especificación (las mismas specs de Diseño UI, en formato de spec) | — (reusa `/screens`) | `project.view` |
| 5 | Pestaña Costos | `GET /usage/summary` acepta `projectId` y agrupa por fase, agente o modelo | `usage.view`; el dinero solo con `cost.view` |
| 6 | Dashboard por perfil | `GET /dashboard` (avance por proyecto, reglas verificadas, último veredicto, fases trabadas, compuertas, escalamientos, consumo del día, presupuestos, conexiones, usuarios activos) | `tenant.view`; dinero con `cost.view` |
| 7 | Buscador global y notificaciones | `GET /search?q=` (proyectos, reglas, agentes, skills, filtrado por permisos), `GET /notifications` (derivadas de tareas, alertas de presupuesto y ejecuciones) | `tenant.view` |
| 8 | Operación de plataforma | `GET /platform/status` (workers con latido, profundidad de colas, trabajos fallidos, ejecuciones en curso) | `superAdmin` o `supportOperator` |
| 9 | E2E, cierre y PR | — | — |

Cada endpoint nuevo lleva su caso en `test_endpoints_authz.py` (permitido, denegado y auditoría si muta) y su prueba
de aislamiento entre tenants. Cada pantalla conectada lleva su prueba E2E con axe.

**Detalles de diseño**

- **Código.** Se sirve la última versión de cada archivo generado (`generated_artifact`), con backend y frontend
  separados. Las rutas se validan contra la tabla: nunca se arma una clave del almacén con texto del cliente.
- **Notificaciones.** Se derivan de datos existentes. No hay tabla nueva. "Leídas" es una marca de tiempo por usuario
  en el navegador: una conveniencia, no un registro.
- **Dashboard del administrador.** El uso se muestra para el tenant activo. El consumo cruzado entre clientes queda
  para Operación de plataforma en M9, porque el libro de consumo está protegido por RLS.

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Ninguna pantalla con backend existente importa `@/mocks/data` | Test de arquitectura en la web: solo Backlog, Autenticación, Integraciones y Seguridad de Administración pueden hacerlo |
| La pestaña Código muestra los archivos generados y descarga el zip solo con permiso | API (authz y aislamiento) y E2E |
| Arquitectura y Contratos muestran el diseño y el OpenAPI de la ejecución | API y E2E |
| Costos cuadra con el libro de consumo, y sin `cost.view` no muestra dinero | API y E2E |
| El Dashboard muestra datos reales por perfil | API y E2E |
| Buscador y notificaciones respetan permisos y tenant | API y E2E |
| Operación de plataforma muestra workers y colas reales, solo para NexTI | API y E2E |

## 4. Cierre de P2 (2026-10-01)

Los criterios de la sección 3 se cumplen con tests automatizados. Ninguna pantalla con backend existente lee datos de
ejemplo; solo la pestaña Backlog (M7b) y los proveedores de identidad de Administración (M0b) siguen con maqueta, y
un test de arquitectura de la web (`src/architecture.test.ts`) falla si otra pantalla vuelve a importarla.

| Criterio | Evidencia (tests) | Estado |
|---|---|---|
| Ninguna pantalla con backend existente importa `@/mocks/data` | `apps/web/src/architecture.test.ts` | ✅ |
| Código: archivos generados y zip solo con permiso | `test_code_api.py`, casos de `test_endpoints_authz.py`, `e2e/code.spec.ts` | ✅ |
| Arquitectura y Contratos muestran el diseño y el OpenAPI | `test_architecture_api.py`, `e2e/architecture.spec.ts` | ✅ |
| Costos cuadra con el libro de consumo; sin `cost.view`, sin dinero | `test_project_usage_api.py`, `test_tokens_without_cost_view_come_without_money`, `e2e/costs.spec.ts` | ✅ |
| Dashboard con datos reales por perfil | `test_dashboard_api.py`, `e2e/dashboard.spec.ts` | ✅ |
| Buscador y notificaciones respetan permisos y tenant | `test_topbar_api.py`, `e2e/topbar.spec.ts` | ✅ |
| Operación de plataforma real, solo NexTI | `test_platform_operations_show_workers_queues_and_failures`, `e2e/platform.spec.ts` | ✅ |

Cada endpoint nuevo tiene su caso de autorización (permitido y denegado) y su prueba de aislamiento entre tenants.
Capturas en `docs/p2/`.

**Suites al cierre.** Backend completo: 735 pasadas, 2 omitidas y 1 fallida, un test del buscador que dependía de que
ningún otro proyecto tuviera reglas con la misma clave; se corrigió (busca una regla con nombre único) y pasa. E2E de
Playwright: 28 de 29; la del Dashboard falló porque los riesgos de otros proyectos llenaban la lista antes que los del
proyecto nuevo; ahora los riesgos van por proyecto, del más reciente al más antiguo, y la prueba pasa.

**Endpoints nuevos:** `GET /projects/{id}/code`, `/code/file`, `/code:download` (auditado), `/design`, `/contracts`,
`/usage`; `GET /dashboard`, `/search`, `/notifications`, `/platform/status`.

**Cambios respecto del plan**

- Los pasos 3 y 4 se hicieron juntos: Arquitectura, Contratos y Pantallas comparten datos.
- El contador de Mis tareas, el Dashboard y las notificaciones reutilizan `GET /tasks`.
- `require_platform` acepta varios roles: Operación de plataforma es para superadministradores y operadores de
  soporte.
- La lista de permisos del proyecto incluye `usage.view` (pestaña Costos).
- Se quitó el distintivo "Prototype · sample data" de la barra superior: las pantallas que siguen con maqueta muestran
  su propio aviso del hito que las conecta.
- Correcciones de accesibilidad heredadas del prototipo que axe detectó al conectar: combobox del buscador con
  `aria-controls`, bloque de código desplazable alcanzable con teclado, barra de presupuesto con nombre accesible y
  contraste de los enlaces "Ver todo".

**Limitaciones conocidas**

- Las notificaciones se derivan de datos existentes (últimos siete días); "leídas" se recuerda por navegador.
- El Dashboard de administrador muestra el cliente activo; el consumo cruzado entre clientes queda para M9.
- Operación de plataforma no muestra versiones por instancia desplegada (M9) ni el detalle de cada sandbox.
- El push a Git es la fase de entrega del pipeline; el botón de la pestaña Código solo lo explica.
