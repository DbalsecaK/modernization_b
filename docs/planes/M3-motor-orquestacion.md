# Plan del hito M3 — Motor de orquestación

- **Estado:** en ejecución (2026-09-29). Se avanza de corrido; solo se detiene ante una decisión importante.
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 10, 11.1, 15.5, 18.4, 18.8, 19.5 y 20 (M3).
- **Rama:** `m3-motor-orquestacion`, un commit por paso, PR a `main` al terminar.
- **Decisiones del aprobador (2026-09-29):** cola sobre PostgreSQL con **Procrastinate** (D-13, ADR-0009) y contenido
  de M3 = **motor completo + preflight real + pipeline de demostración** solo en desarrollo y test.

## 1. Alcance

| Incluye | No incluye (hito) |
|---|---|
| Worker (`apps/worker`) con cola Procrastinate y reanudación tras caída (heartbeat) | Contenido real de las fases de análisis, diseño y generación (verticales M4+) |
| Grafo LangGraph compuesto desde la configuración del proyecto (fases del flujo, compuertas de la plantilla, agentes del equipo) con checkpointer PostgreSQL | Claude Agent SDK (10.5, opcional) |
| Compuertas C1–C4 con `interrupt`: aprobar exige el permiso y respeta la segregación de funciones (16.3) | Sandbox reforzado con gVisor/Firecracker y runners Windows (despliegues, M9) |
| Preguntas (tarjetas de decisión 10.4) con respuesta recomendada, alternativas y respuesta propia; aceptar en bloque las de bajo impacto | Continuar exactamente "todo lo que no depende" de una pregunta con el grafo de conocimiento (llega con Neo4j en M4); en M3 siguen las ramas en curso |
| Patrón hacer → verificar → corregir con máximo de iteraciones y escalamiento a una persona | Veredicto por módulo (11.3, M4) |
| Sandbox Docker sin red, con límites de CPU, memoria, procesos y tiempo | |
| Preflight real: insumos, secretos, repositorio, modelos por agente, presupuesto, y listado del zip dentro del sandbox | |
| Pipeline de demostración determinista (solo desarrollo y test) que ejercita todo el motor | |
| Eventos de ejecución por SSE filtrados por OpenFGA; pestaña Ejecuciones en vivo; bandeja Mis tareas; panel de actividad conectado con descarga del JSON sin secretos | |

## 2. Decisiones de diseño (sin detener el hito)

1. **Cola (D-13, ADR-0009):** Procrastinate sobre el mismo PostgreSQL. La API crea la ejecución y encola su trabajo en
   **la misma transacción**; el worker marca latidos y, si muere, el trabajo se reintenta en segundos. La reanudación
   real la da el checkpoint de LangGraph: el trabajo reintentado continúa desde el último paso completado.
2. **Estado del grafo con referencias, no datos** (10.2): ids de ejecución, fase, invocación, pregunta y claves de
   objetos; los artefactos van al object storage. Por eso las tablas del checkpointer y de la cola (sin `tenant_id`,
   excepción de infraestructura registrada en ADR-0009) no guardan datos del cliente.
3. **Ejecutores de fase como plugins:** un registro `fase → ejecutor`. En M3: `preflight` real y, para el tipo de
   ejecución `demo`, ejecutores deterministas de demostración. Una fase sin ejecutor en esta versión deja la ejecución
   en espera con el motivo "disponible desde M4" (nunca "avanza a medias", 11.1).
4. **Compuertas e interrupciones:** la compuerta es un nodo que llama a `interrupt`; aprobar o rechazar encola la
   reanudación con `Command(resume=…)`. Las plantillas deciden qué compuertas son obligatorias; las demás se registran
   como revisión asíncrona. El nivel de autonomía (10.4) decide además qué se revisa por excepción.
5. **Permiso nuevo `question.answer`** (proyecto) para responder preguntas: dueño, arquitecto, analista y revisor de
   negocio. Se registra en la sección 16.2 (los permisos listados son ejemplos) y en el catálogo.
6. **Eventos:** el worker escribe `activity_event` (con el mismo filtro de secretos que los logs); la API los sirve
   por SSE consultando cada segundo desde el último id, solo de los proyectos que OpenFGA deja ver al usuario.
7. **Sandbox en desarrollo:** el worker usa el Docker local (`docker run --network none --read-only …`, imagen fijada
   por digest). El acceso al socket de Docker equivale a root en esa máquina: aceptable en desarrollo y CI; en
   producción el sandbox es un servicio aparte con gVisor/Firecracker (M9).

## 3. Modelo de datos (migración 0007)

| Tabla | Alcance | Notas |
|---|---|---|
| `run` | tenant (RLS) | proyecto, versión de configuración, tipo (`pipeline`/`demo`), estado, quién la lanzó, límites, fechas |
| `phase_run` | tenant (RLS) | fase, estado, iteraciones, motivo de espera |
| `agent_invocation` | tenant (RLS) | agente, fase, subagente/shard, estado, iteración, modelo, tokens, costo, error redactado |
| `gate` | tenant (RLS) | C1–C4 por ejecución, obligatoria o asíncrona, estado, quién decidió, comentario |
| `question` | tenant (RLS) | tarjeta de decisión completa, estado, respuesta, si fue la recomendada, quién y cuándo |
| `activity_event` | tenant (RLS) | evento del panel (agente, fase, mensaje, estado, tokens, costo, modelo), carga redactada |
| `procrastinate_*`, `checkpoint*` | infraestructura | cola y checkpointer; solo referencias (ADR-0009) |

## 4. Endpoints

| Recurso | Operaciones | Permiso |
|---|---|---|
| `/projects/{id}/runs` | listar, lanzar (`pipeline`; `demo` solo en desarrollo/test) | `project.view` / `pipeline.run` |
| `/runs/{id}` | detalle con fases, invocaciones, compuertas y preguntas; `:cancel` | `project.view` / `pipeline.run` |
| `/runs/{id}/gates/{gate}:approve`, `:reject` | decidir una compuerta (no quien lanzó la ejecución) | `gate.c1/c2/c3.approve`, `signoff.sign` (C4) |
| `/projects/{id}/questions`, `/questions/{id}:answer`, `/questions:accept-recommended` | preguntas del proyecto, responder, aceptar en bloque las de bajo impacto | `project.view` / `question.answer` |
| `/tasks` | Mis tareas: preguntas y aprobaciones de todos los proyectos que el usuario puede resolver | sesión (filtrado por OpenFGA) |
| `/runs/{id}/events`, `/activity/events` (SSE), `/activity/events/{id}/export` | eventos en vivo; JSON de un evento sin secretos | `project.view` (filtrado por OpenFGA) |

## 5. Criterios de aceptación de M3 → tests

| Criterio | Test |
|---|---|
| Matar un worker a mitad de una fase y reanudar sin perder trabajo | Integración con procesos reales: se mata el worker (SIGKILL) dentro de una fase de la demo, otro worker toma el trabajo y la ejecución termina; las fases ya completadas no se repiten (una invocación cada una) |
| Una compuerta detiene el flujo hasta la aprobación de un usuario con el permiso | La ejecución queda esperando en C1; aprobar sin permiso → 403; quien lanzó no puede aprobar su compuerta; con el permiso, la ejecución sigue |
| La autocorrección respeta el máximo de iteraciones | Una fase cuya verificación siempre falla hace exactamente `max_iterations` intentos y escala con una pregunta con el diagnóstico |
| El panel solo muestra eventos de proyectos autorizados y el JSON descargado no contiene secretos | SSE con dos proyectos (uno ajeno) y exportación de un evento cuyo error contenía un token: queda redactado |
| Permitido y denegado por endpoint, aislamiento y auditoría (CLAUDE.md) | Matriz de `test_endpoints_authz.py` y tests de aislamiento |

## 6. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0009 (cola Procrastinate) y D-13 registrada |
| 2 | Migración 0007: ejecuciones, fases, invocaciones, compuertas, preguntas, eventos; cola y checkpointer; permiso `question.answer` |
| 3 | `packages/sandbox`: Docker sin red con límites |
| 4 | `packages/orchestration`: composición del grafo, compuertas, preguntas, hacer → verificar → corregir, ejecutores (preflight y demo) |
| 5 | `apps/worker`: Procrastinate, ejecución y reanudación; eventos redactados |
| 6 | API: ejecuciones, compuertas, preguntas, Mis tareas, SSE y exportación; matriz de autorización y aislamiento |
| 7 | Aceptación del motor: worker muerto y reanudado, compuertas, iteraciones, eventos filtrados |
| 8 | Web: pestaña Ejecuciones en vivo y Resumen con el estado real |
| 9 | Web: Mis tareas y tarjetas de decisión conectadas |
| 10 | Web: panel de actividad conectado al SSE |
| 11 | CI (worker y Docker), cierre y PR |
