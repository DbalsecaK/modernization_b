# Plataforma de Modernización y Construcción Asistida por IA — Especificación

> **Propósito de este documento.** Es la especificación maestra del producto. Sirve para que el equipo y
> Claude Code (en VS Code) construyan la plataforma por hitos. Cada hito de la sección 20 tiene entregables
> y criterios de aceptación verificables. Si algo del código contradice este documento, se corrige el
> código o se actualiza el documento de forma explícita (con una decisión registrada en la sección 22).

- **Producto:** plataforma web multi-cliente para modernizar aplicaciones legacy y construir funcionalidades
  nuevas a partir de documentación, con agentes de IA verificados.
- **Dueño:** NexTI Business Solutions.
- **Estado:** especificación inicial (v0.1).
- **Idioma del producto:** **inglés nativo** (idioma por defecto de toda la plataforma), con cambio a español.
  Ver 18.6.
- **Idioma de este documento:** español.

---

## Índice

1. Visión y alcance
2. Metodología: Spec-Driven Development (SDD)
3. Flujos de la plataforma
4. Modelo de especificación (la spec)
5. Grafo de conocimiento
6. Flujo 1 — Modernización (detalle)
7. Flujo 2 — Nueva funcionalidad desde documentos (detalle)
8. Adaptadores de origen y packs de destino
9. Agentes, subagentes y skills
10. Orquestación multiagente (LangGraph)
11. Verificación, validación y autocorrección
12. Configuración de modelos de IA
13. Consumo de tokens y costos
14. Multi-cliente, multi-proyecto y modelos de despliegue
15. Seguridad
16. RBAC y autorización
17. Administración y configurabilidad
18. Frontend: mapa de la aplicación
19. Arquitectura técnica, stack y estructura del repositorio
20. Roadmap por hitos
21. Aplicaciones de referencia y evaluación
22. Decisiones registradas y pendientes
23. Requisitos no funcionales
24. Glosario
25. Anexo: reutilización del plugin `code-modernization` de Anthropic

---

## 1. Visión y alcance

### 1.1 Problema

Los bancos y aseguradoras tienen sistemas legacy (COBOL, CICS, stored procedures, WebForms) cuya lógica
de negocio está enterrada en el código. Las herramientas de transpilación traducen sintaxis, pero no
explican las reglas ni demuestran que el resultado se comporta igual. Además, construir funcionalidades
nuevas desde historias de usuario y prototipos sigue siendo lento y difícil de trazar.

### 1.2 Propuesta de valor

1. **Entender:** extraer las reglas de negocio y los contratos de datos del legacy, con trazabilidad a
   `archivo:línea`, y documentarlos de forma que negocio los pueda validar.
2. **Construir:** generar el destino desde una especificación aprobada, no desde la estructura del legacy.
3. **Demostrar:** probar equivalencia de comportamiento con evidencia (golden master, inputs frescos,
   canario) y un veredicto calculado por código, no por el modelo.
4. **Gobernar:** plataforma web multi-cliente con roles, aprobaciones, auditoría, control de modelos y
   de costos.

### 1.3 Alcance por versión

| Alcance | Contenido |
|---|---|
| **v1 (este documento)** | Flujo 1 (modernización) y Flujo 2 (nueva funcionalidad desde documentos). Plataforma completa: multi-cliente, RBAC, configuración IA, costos, agentes y skills seleccionables. |
| **Posterior** | Flujo 3 (añadir funcionalidad a una aplicación existente) y Flujo 4 (validación independiente de una migración hecha por un tercero). El diseño de v1 debe dejarlos preparados (ver 3.3). |

### 1.4 Diferenciadores

- Grafo de conocimiento persistente (código + datos + reglas + destino + proceso).
- Especialización en COBOL/CICS/BMS, Sybase y .NET Framework bancario.
- Validación de equivalencia con evidencia auditable y veredicto honesto (PROVEN / PARTLY / NOT PROVEN).
- Plataforma multi-cliente con despliegue en la nube del cliente (el código no sale de su perímetro).

---

## 2. Metodología: Spec-Driven Development (SDD)

### 2.1 Principio

Todo flujo sigue el mismo patrón: **insumo → especificación → código → verificación contra la especificación**.
La especificación es el pivote: es neutral respecto al lenguaje, la revisa un humano y es la única fuente
desde la que se genera código.

- En el **Flujo 1**, la spec se obtiene por **ingeniería inversa** del código legacy.
- En el **Flujo 2**, la spec se obtiene por **ingeniería directa** desde documentos, HU, Figma y capturas.

### 2.2 Patrones de apoyo (no reemplazan a SDD)

| Patrón | Dónde se usa |
|---|---|
| **Strangler fig + anti-corruption layer** | Flujo 1: convivencia y corte progresivo del legacy por dominio. |
| **DDD** (bounded contexts, agregados) | Agrupar reglas y capacidades en servicios o módulos. |
| **Arquitectura hexagonal** (siempre, por dentro) | El dominio queda sin dependencias técnicas; base de datos, nube y UI son adaptadores intercambiables. |
| **BDD / Gherkin** | Lenguaje de las reglas y de los criterios de aceptación. |
| **Tablas de decisión (estilo DMN)** | Lógica tabular (tarifas, comisiones, límites). |
| **Contract-first** (OpenAPI / AsyncAPI) | Los contratos se aprueban antes de generar código. |
| **Characterization tests y golden master** | Capturar y congelar el comportamiento del legacy como oráculo. |
| **Fitness functions** | Reglas de arquitectura ejecutables (capas, dependencias, nombres). |
| **"Constitución" del cliente** | Principios y convenciones que condicionan toda generación. |

### 2.3 Regla de oro

**El agente generador nunca ve el código legacy.** Ve la regla especificada, el contrato de datos y las
convenciones del destino. Así se evita producir código destino que "parece COBOL".

---

## 3. Flujos de la plataforma

### 3.1 Resumen

| Flujo | Origen de la spec | Qué se genera | Cómo se valida | Versión |
|---|---|---|---|---|
| **1. Modernización** | Código legacy (inversa) | Sistema nuevo | Golden master, caracterización, inputs frescos, canario | v1 |
| **2. Nuevo desde documentos** | HU, manuales, Figma, capturas (directa) | Sistema nuevo | Tests de aceptación (Gherkin), contract tests, fidelidad visual | v1 |
| **3. Añadir a lo existente** | Spec AS-IS (inventario) + spec delta | Solo el delta, reutilizando lo existente | Regresión + aceptación + fitness functions | Posterior |
| **4. Validar migración de un tercero** | Dos specs extraídas por separado (original y migrado) | Nada: dictamen | Reconciliación de reglas + pruebas diferenciales | Posterior |

### 3.2 Partes compartidas por los flujos 1 y 2

- Modelo de spec en el grafo (sección 4).
- Compuertas humanas sobre la spec, la UI y la arquitectura.
- Generación por capas con el pack de destino elegido.
- Validación con tests de aceptación y canario.
- Toda la plataforma web (proyectos, avance, trazabilidad, aprobaciones, costos).

### 3.3 Preparación para los flujos 3 y 4 (requisito de diseño en v1)

- El inventario del grafo (APIs, clases, entidades, componentes UI) debe poder construirse **sin** extraer
  reglas completas (necesario para el Flujo 3).
- La extracción de reglas debe poder ejecutarse sobre **dos códigos distintos** y compararse (Flujo 4).
- La validación no debe depender de artefactos generados por la propia plataforma: debe poder recibir
  un "destino" externo.

---

## 4. Modelo de especificación (la spec)

La spec es **dato estructurado** (no Markdown suelto). Vive en el grafo (sección 5) y se proyecta en la
web y en archivos exportables (Markdown, Gherkin `.feature`, OpenAPI YAML, JSON).

### 4.1 Elementos

| Elemento | Campos mínimos |
|---|---|
| **Capacidad** | id, nombre, dominio, actor, objetivo, prioridad, origen |
| **Regla de negocio** | id (`RULE-NNN`), nombre, dominio, categoría (cálculo, validación, ciclo de vida, política), prioridad (P0/P1/P2), enunciado en lenguaje de negocio, condición y acción formalizadas, datos de entrada/salida con tipo neutral, escenarios Given/When/Then con **valores concretos**, parámetros hardcodeados, defecto sospechado, confianza, pregunta para el SME, origen |
| **Tabla de decisión** | id, entradas, salidas, filas, política de acierto, origen |
| **Pantalla** | id, nombre, campos (tipo, longitud, obligatorio, formato, validación, mensaje de error), acciones, estados (vacío, cargando, error, éxito), navegación de entrada y salida, origen |
| **Contrato** | id, operación, entrada, salida, errores, idempotencia, seguridad; proyección a OpenAPI/AsyncAPI |
| **Entidad de dominio** | id, atributos con tipo neutral, invariantes, agregado al que pertenece |
| **Requisito no funcional** | id, categoría (seguridad, auditoría, rendimiento, disponibilidad), criterio medible |
| **Restricción de arquitectura** | id, regla (capas, dependencias, nombres), fitness function asociada |
| **Caso de prueba** | id, tipo (aceptación, caracterización, golden master, contrato, visual), entrada, salida esperada, reglas que verifica |
| **Pregunta abierta** | id, pregunta, contexto, evidencia, motivo, impacto (alto/bajo), opciones con justificación y confianza, opción recomendada, elementos afectados, responsable, estado, respuesta, quién respondió (sección 10.4) |
| **Flujo de negocio** | id, nombre, persona, resumen, reglas involucradas, pasos ordenados (título, nodos del grafo que recorre, regla que aplica), origen (reconstruido del grafo y de las reglas, validado por negocio) |

### 4.2 Origen trazable (obligatorio en todo elemento)

Cada elemento guarda **de dónde salió**:

- Flujo 1: `archivo:línea-inicio-fin` del legacy (y el slice que lo justifica).
- Flujo 2: documento + página/sección, HU (id externo), frame de Figma (file key + node id) o captura.
- Decisión humana: usuario, fecha y comentario.

### 4.3 Catálogo de tipos neutrales

Todo dato se tipa con un tipo neutral, independiente del origen y del destino:

- `decimal(p, s, signed)`, `integer(bits, signed)`, `text(fixed|var, len, encoding)`,
  `date(format)`, `timestamp(tz)`, `boolean`, `binary(len)`, `enum(valores)`.
- Cada adaptador de origen mapea hacia estos tipos (p. ej. `PIC S9(7)V99 COMP-3` → `decimal(9,2,signed)`).
- Cada pack de destino mapea desde ellos (p. ej. `decimal(9,2)` → `BigDecimal` en Java, `decimal` en .NET,
  `NUMERIC(9,2)` en PostgreSQL).
- Se registran diferencias sensibles: orden de clasificación (EBCDIC vs ASCII), collation, manejo de NULL,
  redondeo, zonas horarias.

### 4.4 Estados de un elemento de la spec

`borrador → en revisión → aprobado → (reabierto) → obsoleto`. Un elemento aprobado solo cambia reabriéndolo,
y reabrirlo invalida lo que depende de él (calculado recorriendo el grafo).

---

## 5. Grafo de conocimiento

Un solo grafo por proyecto, con capas. Tecnología: **Neo4j 5** (Cypher, GDS para comunidades y centralidad,
índice vectorial para búsqueda semántica). El texto del código **no** se guarda en el grafo: solo
referencias a archivo y línea; el fuente vive en el object storage.

### 5.1 Capas, nodos y aristas

| Capa | Nodos | Aristas |
|---|---|---|
| **Código (estructural)** | Programa, Párrafo/Sección, Copybook, Campo, Tabla, Columna, Archivo, MapaBMS, Transacción, Job, Step, StoredProcedure, Página ASPX, Clase, Método | `CALLS`, `COPIES`, `PERFORMS`, `READS`, `WRITES`, `EXEC_SQL`, `EXEC_CICS`, `USES_MAP`, `STARTS`, `INVOKES` |
| **Datos (semántica)** | Campo con tipo de origen y tipo neutral | `MOVES_TO`, `DERIVES_FROM`, `REDEFINES` |
| **Conocimiento (funcional)** | Capacidad, Regla, TablaDecisión, Dominio, Pantalla, Contrato, Entidad, CasoPrueba, Pregunta, Insumo | `DERIVED_FROM` (→ párrafo o insumo), `READS`/`PRODUCES` (→ campo), `BELONGS_TO` (→ dominio), `VERIFIES` (caso → regla), `SHOWN_IN` (campo → pantalla) |
| **Destino (TO-BE)** | Servicio, Módulo, Clase, Método, Endpoint, Entidad destino, Componente UI, Test | `IMPLEMENTS` (→ regla/contrato/pantalla), `MAPS_TO` (campo origen → propiedad destino) |
| **Proceso** | Ejecución, Fase, InvocaciónAgente, Aprobación, Veredicto | `PRODUCED_BY`, `APPROVED_BY`, `VERIFIED_IN` |

### 5.2 Consultas que el grafo debe responder (requisitos)

- Impacto: "¿qué se rompe si cambio este copybook / tabla / campo?"
- Dominios: "¿qué programas forman el dominio X?" (comunidades sobre tablas compartidas).
- Cobertura: "¿esta regla tiene un caso de prueba que pasó?"
- Trazabilidad inversa: "¿de dónde sale este método?" (Método → Regla → Párrafo → línea).
- Reglas dispersas: "¿qué reglas de varios programas afectan al mismo campo de salida?"
- Orden de migración: ordenamiento topológico con peso por complejidad. Es una **sugerencia**: se presenta
  como plan por olas de historias de usuario que las personas pueden cambiar, validado contra el grafo (7.7).
- Completitud (ver 11.5).
- Huérfanos y aislados: "¿qué programas, copybooks o archivos no usa nadie?" (candidatos a código muerto o
  datos sin uso) y "¿qué elementos no tienen ninguna relación?" (posibles referencias faltantes).
- Flujos de negocio: "¿qué recorrido hace el flujo X, en qué orden y qué reglas aplica en cada paso?"

### 5.2.1 Visualización del grafo (pestaña Inventario)

- **Recorrido de flujos de negocio:** combobox con los flujos identificados (nombre + persona). Al elegir uno,
  el grafo resalta su recorrido con pasos numerados y atenúa el resto; un panel lateral lista los pasos (nodos
  que recorre y regla que aplica), permite avanzar y retroceder y enlaza cada regla con la vista
  Origen ↔ destino.
- **Foco por regla de negocio:** combobox con las reglas extraídas; resalta los nodos que la implementan y sus
  vecinos directos, y muestra en qué flujos participa.
- **Filtros de relaciones:** llamadas/inicios, lecturas, escrituras e inclusiones (copybooks, mapas), cada una
  con su estilo de línea y dirección (flechas).
- **Filtro de nodos:** todos, **solo huérfanos y aislados**, u ocultarlos; además, filtro por tipo de nodo.
  Los huérfanos y aislados se marcan con borde punteado y una explicación en el detalle.
- **Dos vistas del mismo grafo:** **Círculos** (empaquetado circular anidado: sistema → dominios con sus
  programas, mapas y copybooks, y un grupo aparte de datos; el tamaño refleja las líneas de código; las
  relaciones se dibujan como arcos) y **Capas** (puntos de entrada → programas → mapas y copybooks → datos).
  Todas las funciones (flujos, reglas, filtros, selección, impacto, huérfanos) aplican en ambas.
- **Color** por dominio o por estado de migración (verificado, generado, en curso, pendiente), con leyenda.
- **Buscador** de módulos, datos y jobs; **zoom** con la rueda o botones, **arrastre** para mover, ajuste
  automático al ancho y restablecer con Esc.
- **Detalle del nodo:** tipo, dominio, estado, líneas de código, destino, relaciones (usa / lo usan), reglas y
  análisis de impacto.

### 5.3 Aislamiento

- Preferido: una base Neo4j por tenant (requiere edición Enterprise).
- Mínimo aceptable: particionado por etiqueta `tenant_id`/`project_id` con filtros **obligatorios** aplicados
  en una única capa de acceso (ningún módulo ejecuta Cypher sin pasar por ella).

### 5.4 Contexto para los agentes

El contexto que recibe un agente se arma con una **consulta al grafo** (el slice, los copybooks y campos
involucrados, quién lo llama), no entregando archivos completos. Esto mantiene el contexto pequeño y reduce
alucinaciones.

---

## 6. Flujo 1 — Modernización (detalle)

### 6.1 Fases

| # | Fase | Qué hace | Salida | Compuerta |
|---|---|---|---|---|
| 1 | **Preflight** | Verifica insumos, toolchain, qué puede ejecutarse localmente; marca de tiempo del legacy | Informe de preflight | — |
| 2 | **Inventario** | Parseo determinista (sin IA) → capa de código y datos del grafo | Mapa del legacy, métricas | — |
| 3 | **Mapa de dominios** | Comunidades del grafo → propuesta de bounded contexts; orden de migración | Dominios y plan | — |
| 4 | **Clasificación** | Cada párrafo/bloque: infraestructura, flujo de control o lógica de negocio | Etiquetas en el grafo | — |
| 5 | **Extracción de reglas** | Program slicing sobre el grafo + agente sobre cada slice → reglas estructuradas; revisor verifica cada cita y la cobertura del slice | Catálogo de reglas, huecos de cobertura | — |
| 6 | **Revisión de reglas e historias** | Negocio revisa, responde preguntas, corrige; revisa y edita las **historias de usuario** derivadas de reglas, pantallas y contratos y el **plan de migración por olas** (7.7) | Reglas, HU y plan aprobados | **C1: spec aprobada** |
| 7 | **UI** | Pantallas legacy (BMS, ASPX) → spec de pantalla → design system y prototipo propuestos | Prototipos | **C2: UI aprobada** |
| 8 | **Diseño** | Bounded contexts, modelo de dominio, contratos OpenAPI, ADR, fitness functions | Diseño | **C3: arquitectura aprobada** |
| 9 | **Caracterización** | Tests de caracterización y golden master del legacy **antes** de generar | Oráculo congelado | — |
| 10 | **Generación por capas** | Contratos → dominio → adaptadores → orquestación; cada capa compila y pasa sus tests antes de la siguiente | Código destino | — |
| 11 | **Verificación independiente** | Re-ejecución limpia, equivalencia, inputs frescos, canario, fuente intacta → veredicto por módulo | Proof pack | **C4: sign-off** |
| 12 | **Endurecimiento** | Seguridad, dependencias, rendimiento básico | Informe | — |
| 13 | **Entrega** | Descarga o push a Git; plan de strangler fig (enrutamiento por dominio, ACL) | Release | — |

### 6.2 Reglas del flujo

- La plataforma **nunca modifica** el legacy. Escribe todo en su propio workspace.
- Trabajo por **unidad funcional** (dominio o módulo), no por archivo.
- La infraestructura del legacy (manejo de archivos, status codes, formateo de pantalla) **no se traduce**:
  la reemplaza el framework destino.
- Si el legacy no puede ejecutarse localmente (típico en CICS), la validación se basa en trazas grabadas
  y el veredicto máximo es **PARTLY PROVEN** (y así se informa).

### 6.3 Convivencia (strangler fig)

- El destino se pone delante del legacy y se enruta un dominio a la vez.
- Un anti-corruption layer traduce entre el modelo de datos viejo y el nuevo mientras ambos existan.
- La plataforma genera el plan de corte por dominio y los stubs del ACL.

---

## 7. Flujo 2 — Nueva funcionalidad desde documentos (detalle)

### 7.1 Insumos aceptados

- Documentos: Word, PDF, Excel, Markdown, manuales de usuario.
- Historias de usuario: archivo o integración (Jira, Azure DevOps).
- Figma: link o archivo (lectura de estructura vía API: frames, componentes, textos, variables/tokens,
  navegación del prototipo).
- Capturas de pantalla y mockups (visión).
- Links a prototipos existentes (Figma *proto* u otra URL navegable) con notas de qué respetar.
- Nada de UI: la plataforma **propone** design system y prototipos (7.4).

**Cuándo se cargan.** Las referencias de UI (capturas, links de Figma y links de prototipos) se pueden cargar
**desde la creación del proyecto** (paso 2 del asistente, sección 18.3) y también después, desde la pestaña
**Insumos** o desde **Diseño UI** (botones *Agregar capturas*, *Agregar Figma*, *Agregar prototipo*). En el
Flujo 1 las mismas referencias sirven para modernizar la UI legacy (BMS, ASPX) hacia un diseño objetivo.
Todo insumo pasa por la misma validación (tipo y tamaño, seguridad de archivos comprimidos, malware,
secretos, versionado; sección 15.4) antes de que un agente lo lea.

### 7.2 Fases

| # | Fase | Qué hace | Compuerta |
|---|---|---|---|
| 1 | **Ingesta** | Cada insumo con su lector; versión y hash de cada insumo | — |
| 2 | **Normalización** | Insumo → elementos de la spec (capacidades, HU normalizadas con Gherkin, pantallas, reglas, contratos, entidades, RNF) con origen | — |
| 3 | **Consolidación** | Cruce HU ↔ pantallas ↔ entidades; detección de **contradicciones** y **huecos** (reglas deterministas sobre el grafo + agente) → preguntas | — |
| 4 | **Revisión de spec** | PO responde preguntas, revisa y edita las HU y el plan de incrementos (7.7) y aprueba | **C1** |
| 5 | **UI** | Figma/capturas → spec de pantalla, o propuesta de design system + prototipos navegables; comentarios e iteración | **C2** |
| 6 | **Diseño** | DDD, modelo de dominio, contratos OpenAPI primero, ADR | **C3** |
| 7 | **Generación por capas** | OpenAPI → esqueletos backend + cliente tipado frontend (determinista); dominio desde reglas; pantallas con el design system | — |
| 8 | **Validación** | Aceptación (Gherkin → Cucumber/Playwright o equivalente del stack), contract tests, fidelidad visual contra Figma/prototipo, accesibilidad, seguridad, canario | **C4** |
| 9 | **Entrega** | Descarga o push a Git | — |

### 7.3 Huecos que se detectan sin IA (ejemplos de reglas sobre el grafo)

- Campo de entrada sin validación.
- Acción de pantalla sin contrato.
- Pantalla sin estado de error o sin estado vacío.
- Botón del prototipo que no navega a ningún lado.
- HU sin criterios de aceptación o regla sin valores concretos.
- Entidad sin dueño (agregado) o contrato sin manejo de errores.

### 7.4 Propuesta de design system y prototipos

- **Design system:** tokens (color, tipografía, espaciado, bordes) y componentes base (formularios, tablas,
  modales, navegación). Se deriva de la marca del cliente si la entrega (logo, colores, web actual); si no,
  se parte del design system base de NexTI. Se muestra como catálogo de componentes con sus estados.
- **Prototipos:** HTML/React real renderizado en la plataforma (navegable, con estados). El cliente comenta
  sobre la pantalla y la plataforma regenera.
- **Aprobación:** el design system y los prototipos aprobados pasan a ser la fuente de verdad de la UI.
- Exportar a Figma queda como opción posterior (la API REST de Figma es de lectura; escribir requiere plugin).
- Las pantallas legacy del Flujo 1 (BMS, ASPX) usan este mismo mecanismo.

**Chat de cambios al prototipo (D-24).** En **Diseño UI** hay un chat con el agente *UX/UI designer* para
pedir cambios en lenguaje natural sobre la pantalla seleccionada ("agrupa límites y saldos", "versión
móvil", "agrega estados de error"), con sugerencias rápidas y la opción de adjuntar una imagen de
referencia.

- Cada pedido aceptado genera una **nueva versión del prototipo** (v1, v2, v3…) enlazada a la spec de
  pantalla; el historial del chat queda como evidencia de la decisión de diseño.
- Si el cambio altera la spec (un campo nuevo, una validación, una acción), el agente lo propone como
  cambio de spec y, si toca algo aprobado, genera una **pregunta** (10.4) en lugar de aplicarlo en silencio.
- El prototipo generado se renderiza en el sandbox (regla 4); los adjuntos son insumo no confiable (regla 5).
- La aprobación sigue siendo la compuerta **C2**: el chat itera, no aprueba.

### 7.5 Definición de "completo" en el Flujo 2

- Todo criterio de aceptación aprobado tiene un test que pasó.
- Todo frame/prototipo aprobado tiene su pantalla implementada.
- Todo campo tiene validación definida y probada.
- Todo endpoint del contrato está implementado y cubierto.
- No quedan preguntas abiertas.

### 7.6 Integración con Jira y Azure DevOps (backlog y ciclo de bugs)

Los agentes mantienen sincronizado el backlog del cliente en **Jira** (Cloud o Data Center) o **Azure DevOps
Boards** (D-22). Aplica a los dos flujos.

**Dónde se configura**

- **Conexión, por tenant:** en *Administración → Integraciones* (sección 17). URL del sitio u organización,
  credencial (OAuth o token en Vault, nunca en el repositorio), alcance y prueba de conexión.
- **Vínculo, por proyecto:** en el paso 2 del asistente (sección 18.3) o después en la pestaña **Backlog**. Se
  elige la conexión del tenant y el proyecto de Jira o Azure DevOps (clave `CARDS` o nombre del proyecto).
- **Mapeo de tipos** configurable: Feature → Epic (Jira) / Feature (ADO); Historia → Story / User Story;
  Tarea → Sub-task / Task; Bug → Bug.

**Reglas de automatización (activables por proyecto)**

| Regla | Qué hace |
|---|---|
| Crear desde la spec | Al aprobar **C1**, crea en Jira/ADO las features, **las historias aprobadas** (7.7, con sus criterios Gherkin) y sus tareas, enlazadas a las reglas y pantallas de la spec y ordenadas por ola |
| Marcar como terminado | Cuando la verificación de un elemento pasa, el agente mueve el ítem a *Done* con la evidencia enlazada |
| Bug ante fallo | Cuando un test o una equivalencia falla, el agente **tester** crea un bug con pasos, esperado vs obtenido, regla y traza |
| Corrección automática | El agente **developer** toma el bug, propone la corrección en el sandbox y la deja en revisión |
| Re-test y cierre | El tester re-ejecuta; si pasa, cierra el bug; si no, lo reabre con el nuevo resultado |
| Sincronizar comentarios | Los comentarios del ítem externo entran como insumo (no confiable) y los de la plataforma se publican |

**Ciclo del bug:** detectado → bug creado → developer activado → corrección propuesta → re-test → espera
revisión humana. La corrección respeta el **nivel de autonomía** del proyecto y el **máximo de iteraciones**
de autocorrección (11.1) según la autonomía (10.4); al superarlo, escala a una persona. El veredicto lo sigue calculando código
determinista (regla 6): cerrar un bug en Jira no cambia un veredicto.

**Reglas de seguridad:** la integración usa la credencial del tenant con alcance mínimo; toda escritura en el
sistema externo queda en la auditoría; el contenido que viene de Jira/ADO es input no confiable (prompt
injection); las escrituras son idempotentes (clave externa guardada en `work_item_link`) y reintentables.

### 7.7 Historias de usuario y plan de migración (ambos flujos)

Antes de iniciar la migración o la construcción, las personas ven y aprueban **qué se va a construir y en qué
orden** (D-25). Está en **Especificación → Historias de usuario** y **Especificación → Plan de migración**; el
Resumen y Mis tareas avisan cuando hay HU pendientes de revisión.

**Origen de las HU**

- **Flujo 1:** el agente *Analista funcional* agrupa reglas, pantallas y contratos extraídos del legacy en
  HU por feature o capacidad (por ejemplo, transacción CAUP → programa → mapa = "Ver y actualizar una
  cuenta"). Cada HU guarda su origen en el legacy.
- **Flujo 2:** vienen de documentos, Figma o Jira/Azure DevOps y se normalizan (fase 2 de 7.2).

**Contenido de cada HU:** feature, título, narrativa "Como… quiero… para…", criterios de aceptación en
Gherkin, vínculos a reglas (`RULE-NNN`), pantallas, contratos y componentes legacy, origen (extraída,
documento, Jira/ADO o creada por una persona), prioridad, estimación, ola, dependencias, estado (borrador,
en revisión, pregunta abierta, aprobada, descartada, fusionada) y versión.

**Lo que pueden hacer las personas**

| Acción | Reglas |
|---|---|
| Editar | Título, narrativa, criterios, vínculos, prioridad, estimación, dependencias. Cada guardado crea una versión |
| Crear | HU manual con origen "persona"; si no se vincula a ninguna regla, pantalla, contrato o componente queda marcada **sin trazabilidad** |
| Dividir | Se eligen los criterios y reglas que pasan a la nueva HU; los vínculos se conservan y las dos vuelven a revisión |
| Fusionar | Se unen criterios, vínculos y dependencias; la HU absorbida queda como "fusionada" y quien dependía de ella pasa a depender de la resultante |
| Descartar | Motivo obligatorio. Si deja reglas sin cubrir, se avisa; puede marcarse **fuera de alcance** (las reglas se migran tal cual, sin HU) |
| Restaurar | Una HU descartada vuelve a revisión y al plan |
| Aceptar sugerencias | El agente sugiere (criterio faltante, HU demasiado grande, estado de error sin cubrir); nada se aplica hasta que una persona lo acepta |

**Cobertura (determinista):** toda regla, pantalla y contrato de la spec debe estar en al menos una HU
activa; lo que no, se muestra como hueco. Las HU sin trazabilidad y las fuera de alcance se listan aparte.

**Validación de los criterios de aceptación (Gherkin, determinista, D-26).** Cada criterio es un escenario y
se valida por código, en vivo al editar y en el servidor al guardar:

| Chequeo | Qué exige |
|---|---|
| Encabezado | Empieza con `Scenario:` / `Escenario:` (o `Scenario Outline:` / `Esquema del escenario:`) y tiene nombre |
| Pasos | Al menos un `Given`, un `When` y un `Then` (o `Dado`, `Cuando`, `Entonces`); `And`/`But` (`Y`/`Pero`) solo continúan un paso anterior |
| Orden y alcance | Given → When → Then; un `When` o `Given` después de un `Then` indica dos comportamientos: se pide dividir el escenario |
| Contenido | Ningún paso vacío ni línea de texto libre que no sea un paso (se permiten tablas de datos, doc strings, comentarios y etiquetas) |
| Esquemas | Un `Scenario Outline` tiene tabla `Examples` con filas, y cada `<placeholder>` es una columna de la tabla |
| Unicidad | No hay dos escenarios con el mismo nombre en la HU |

Las palabras clave se aceptan en inglés y en español (idioma de artefactos, 18.6). Un formulario con errores
no se guarda; una HU importada con criterios inválidos (por ejemplo desde Jira o un documento) se marca y
**bloquea C1** hasta corregirla. La validación es de forma: que el escenario describa bien la regla lo revisa
una persona, y que se cumpla lo prueba el test generado desde el escenario (11.4).

**Plan de migración por olas**

- La plataforma **propone** el plan desde el grafo (5.2): cada HU va en la ola siguiente a la más tardía de
  la que depende; dentro de la ola, por prioridad y luego por tamaño. Las dependencias entre HU salen de las
  relaciones del grafo (lee/escribe la misma tabla, llama al programa, usa la pantalla) y las personas pueden
  agregar otras.
- Las personas **cambian el orden**: arrastran HU entre olas, las reordenan dentro de la ola, crean olas y
  pueden volver al orden sugerido. Se muestra la diferencia "sugerido vs el tuyo".
- **Validación por código, no por modelo**, en cada cambio:
  - **Dependencia dura** (p. ej. la tabla aún no existe en el destino): el movimiento se **rechaza** con el motivo.
  - **Dependencia blanda**: se permite con **aviso** y se planifica una ACL o stub temporal (strangler fig, 6.3).
  - Una HU puede compartir ola con su dependencia (se construyen juntas), nunca ir antes.
- El plan se aprueba en **C1** junto con las HU. C1 **no se puede aprobar** si hay HU con preguntas abiertas,
  sin criterios de aceptación, con **criterios Gherkin inválidos** o con dependencias duras rotas en el plan.

**Después de C1:** todo cambio es un **cambio de alcance**: solo las HU afectadas vuelven a revisión, se
recalcula el impacto en el grafo, se sincroniza con Jira/Azure DevOps (7.6) y, si la HU ya está en
construcción o terminada, se genera una **pregunta** (10.4) en lugar de aplicarlo en silencio. Un cambio
hecho en Jira entra como insumo a revisar, no modifica la spec directamente.

**Permisos (OpenFGA):** el product owner y el analista funcional editan HU; el product owner y el líder
técnico cambian el plan; el ejecutivo solo ve. Toda acción queda versionada y en la auditoría.

---

## 8. Adaptadores de origen y packs de destino

### 8.1 Principio N+M

Cada origen solo sabe llegar a la spec; cada destino solo sabe salir de ella. Nunca se construye un
migrador por par origen→destino.

### 8.2 Contrato del adaptador de origen

Todo adaptador implementa:

1. `detect(insumos) → confianza` — reconoce si el insumo es de su tecnología.
2. `inventory(workspace) → nodos y aristas` de las capas de código y datos.
3. `types() → mapeo` de tipos de origen a tipos neutrales.
4. `classify_hints()` — pistas técnico/funcional propias del lenguaje.
5. `slice(salida) → slice` — program slicing (si el nivel lo permite).
6. `screens() → specs de pantalla` (si el origen tiene UI).
7. `runner()` — cómo ejecutar el legacy para golden master (si es posible) o cómo importar trazas.

### 8.3 Orígenes (v1)

| Origen | Puntos críticos | Validación |
|---|---|---|
| **COBOL batch** (+ JCL, copybooks, VSAM/secuencial) | COMP-3, zoned, EBCDIC; orden de clasificación; JCL → orquestación | Golden master ejecutable (p. ej. GnuCOBOL) cuando sea posible |
| **COBOL CICS** | Pseudo-conversacional, COMMAREA/channels, `EXEC CICS` (LINK, XCTL, READ, SYNCPOINT) | Trazas grabadas; techo PARTLY PROVEN si no corre localmente |
| **Mapas BMS** | Parseo determinista de `DFHMSD/DFHMDI/DFHMDF`: posición, longitud, atributos (PROT, UNPROT, NUM, BRT) | Comparación campo a campo |
| **Stored procedures Sybase ASE** | Tablas temporales, cursores, `@@error`/`@@rowcount`, modo chained, NULL, conversiones implícitas, fechas; decisión: lógica en BD o en servicio | Golden master con ambos motores y los mismos datos |
| **ASPX / C# .NET Framework** | WebForms (ViewState, postbacks, code-behind, server controls), `web.config`, ADO.NET, WCF | Ejecutable con runner Windows; dos caminos: *uplift* a .NET 10 o reescritura |

CICS + BMS se tratan como **una familia**: `Transacción → Programa → Mapa`.

### 8.4 Pack de destino

Se combinan cinco ejes:

| Eje | Opciones v1 y posteriores |
|---|---|
| **Arquitectura** | Microservicios, monolito modular, MVC, serverless, event-driven, BFF |
| **Backend** | Java Spring Boot, Java Quarkus, .NET 10, Go, Next.js (fullstack/BFF) |
| **Frontend** | React, Angular, Next.js |
| **Persistencia** | PostgreSQL, MySQL, SQL Server, Oracle, MongoDB |
| **Cloud / despliegue** | AWS, Azure, GCP, Kubernetes genérico / on-prem |

Cada pack aporta: plantillas y convenciones, generadores deterministas (OpenAPI → código, esquema →
entidades), mapeo de tipos neutrales, frameworks de test, comandos de build/ejecución, fitness functions,
IaC (Terraform/OpenTofu como base) y mapeo de conceptos legacy a servicios gestionados
(JCL → Step Functions / Logic Apps / Workflows; MQ → SQS / Service Bus / Pub/Sub).

### 8.5 Matriz de compatibilidad (reglas, no solo tabla)

Ejemplos de reglas que el asesor de arquitectura aplica y registra como ADR:

- **MongoDB** exige un paso adicional de modelado de agregados (qué se embebe y qué se referencia).
- **Serverless** no admite procesos largos (batch de horas → servicios de batch/orquestación, no funciones).
- **CICS pseudo-conversacional** encaja bien en servicios stateless o serverless.
- **Next.js** puede ser frontend o frontend + BFF: cambia qué se genera en el backend.
- **Quarkus y Spring Boot** comparten el núcleo Java: un pack con adaptadores de framework distintos.
- **Go** tiene su propio pack con convenciones idiomáticas (no traducción del pack Java).
- Diferencias de base de datos (collation, NULL, fechas) se toman del catálogo de tipos neutrales.

### 8.6 Niveles de soporte

| Nivel | Significado |
|---|---|
| **Certificado** | Parser real, tipos exactos, golden master automatizado, aplicación de referencia con suite de evaluación en cada versión, modelos con los que fue certificado |
| **Asistido** | tree-sitter o análisis con LLM, grafo aproximado, más revisión humana; el veredicto lo indica |
| **Experimental** | Solo agentes; para evaluación |

### 8.7 Olas de certificación

- **Ola 1:** orígenes COBOL batch, COBOL CICS + BMS, Sybase SP, ASPX/.NET Framework. Destinos Java Spring
  Boot, .NET 10, Angular, React, PostgreSQL, SQL Server, Oracle, AWS y Azure en contenedores.
- **Ola 2:** Quarkus, Next.js, MySQL, GCP, serverless.
- **Ola 3:** Go, MongoDB.

---

## 9. Agentes, subagentes y skills

### 9.1 Conceptos

- **Agente:** un rol ("quién"). Plantilla de nodo o subgrafo LangGraph con responsabilidades, fases,
  herramientas permitidas y capacidades de modelo requeridas.
- **Subagente:** instancia de un agente lanzada en paralelo (fan-out) sobre una porción del trabajo
  (p. ej. un extractor por módulo).
- **Skill:** paquete de conocimiento ("saber cómo"): instrucciones, convenciones, ejemplos, plantillas y
  scripts opcionales. Formato compatible con las skills de Claude (`SKILL.md` con metadatos + recursos).

### 9.2 Ficha de un agente

| Campo | Descripción |
|---|---|
| `id`, `nombre`, `icono`, `version` | Identidad |
| `descripcion_corta` | 2–3 líneas para la card |
| `grupo` | Análisis, Diseño, Construcción, Calidad, Control |
| `responsabilidades` | Qué artefactos produce |
| `fases` | En qué fases actúa |
| `capacidades_modelo` | tool calling, visión, contexto largo, salida estructurada |
| `herramientas` | Lista blanca (leer grafo, leer código, escribir workspace, ejecutar en sandbox…) |
| `skills_compatibles` | Filtros por origen/destino/arquitectura |
| `perfil_modelo_default` | Referencia a un perfil (sección 12) |
| `obligatorio` | `true` para los agentes de Control |
| `nivel` | Certificado / asistido / experimental |
| `prompt_sistema` | Versionado |
| `eval` | Resultados en las aplicaciones de referencia |

### 9.3 Catálogo inicial de agentes

| Grupo | Agentes |
|---|---|
| **Análisis** | Analista legacy, Extractor de reglas de negocio, Analista de datos, Analista de UI (BMS, ASPX, Figma, capturas), Analista funcional (HU y documentos) |
| **Diseño** | Arquitecto de soluciones, Arquitecto de datos, Diseñador UX/UI |
| **Construcción** | Backend developer, Frontend developer, Full stack developer, Ingeniero de migración de datos, DevOps / Cloud engineer |
| **Calidad** | Test engineer, Revisor de código, Auditor de seguridad |
| **Control (obligatorios)** | Verificador de reglas, Validador de equivalencia, Juez de aceptación |

### 9.4 Selección del equipo en el proyecto

1. **Propuesta determinista:** una matriz (flujo × origen × destino × arquitectura → agentes) arma el
   equipo recomendado, con el motivo de cada recomendación.
2. **Ajuste del usuario:** reemplazar (p. ej. Backend + Frontend → Full stack, mostrando consecuencias),
   quitar o agregar.
3. **Validación de la composición:**
   - Toda fase tiene al menos un agente responsable.
   - Los agentes de Control **no se pueden quitar** (solo cambiar su modelo).
   - Cada agente tiene un perfil de modelo compatible con sus capacidades.
4. Los cambios posteriores afectan solo a fases no iniciadas y quedan en la auditoría.

### 9.5 Ficha de una skill

| Campo | Descripción |
|---|---|
| `id`, `nombre`, `version`, `descripcion_corta` | Identidad (la descripción es lo que el agente ve siempre) |
| `tipo` | Origen, destino, conversión, transversal, cliente |
| `aplica_a` | Agentes, orígenes, destinos, arquitecturas |
| `conflictos` | Skills incompatibles (p. ej. Spring Boot vs Quarkus en el mismo agente) |
| `requiere` | Skills de las que depende |
| `contenido` | `SKILL.md` + recursos (plantillas, ejemplos, scripts) |
| `eval` | Resultados en las aplicaciones de referencia |
| `estado` | Borrador, en evaluación, publicada, obsoleta |
| `ambito` | Global (NexTI) o del tenant |

### 9.6 Ejemplos de skills

| Tipo | Ejemplos |
|---|---|
| **Origen** | Semántica COBOL (COMP-3, zoned, EBCDIC), EXEC CICS, parseo BMS, T-SQL de Sybase, WebForms/ViewState |
| **Destino** | Spring Boot hexagonal, Quarkus, .NET 10 minimal APIs, Angular + Material, React + design system, PL/pgSQL, IaC AWS/Azure |
| **Conversión** | CICS pseudo-conversacional → REST stateless, BMS → formularios Angular/React, Sybase SP → servicio Java o PL/pgSQL, VSAM → PostgreSQL |
| **Transversal** | OWASP secure coding, generación de Gherkin, contract-first OpenAPI, golden master, WCAG |
| **Cliente** | Convenciones del banco, design system del cliente, constitución de arquitectura |

### 9.7 Selección de skills en el proyecto

- Tras definir el equipo, la plataforma propone skills cruzando `aplica_a` con el proyecto.
- Se muestran agrupadas por agente, con recomendadas marcadas, **conflictos** en rojo y **faltantes**
  advertidos ("el origen incluye BMS y no hay skill de parseo BMS activa").
- **Carga progresiva:** el agente ve siempre la descripción corta de sus skills y carga el contenido completo
  solo cuando la tarea lo requiere.
- **Versionado:** el proyecto fija versiones de agentes y skills; actualizar es una acción explícita.
- **Agentes y skills propias** (tenant o NexTI): flujo de aprobación + evaluación antes de publicarse.

---

## 10. Orquestación multiagente (LangGraph)

### 10.1 Estructura

- **Grafo del flujo:** supervisor que recorre las fases y se detiene en las compuertas (`interrupt`).
- **Subgrafo por fase:** agentes especialistas de la fase.
- **Fan-out de subagentes:** paralelismo por módulo/shard con límite de concurrencia configurable.
- El grafo se **compone dinámicamente** a partir del equipo y las skills elegidos, y se valida antes de ejecutar.

### 10.2 Estado y durabilidad

- Checkpointer en **PostgreSQL**: cada ejecución puede pausarse, reanudarse tras un fallo y esperar una
  aprobación humana sin perder estado.
- Los checkpoints referencian nodos del grafo de conocimiento (no copian datos grandes).
- Los artefactos grandes (código, salidas, logs) van al object storage; el estado guarda referencias.

### 10.3 Ejecución

- La API **nunca** ejecuta agentes: encola trabajos que toman **workers** separados.
- Todo lo que compila o ejecuta código corre en el **sandbox** (sección 15.5).
- Eventos de progreso publicados en tiempo real (SSE/WebSocket) hacia la web.

### 10.4 Autonomía y human in the loop (decisión D-21)

Principio: **la persona interviene donde aporta, no en cada fase.** Aprobar todo cansa y termina en
aprobaciones sin leer. Hay tres mecanismos:

| Mecanismo | Cuándo interviene la persona |
|---|---|
| **Compuertas** (C1–C4) | En cuatro momentos: spec, UI, arquitectura y sign-off. La plantilla del proyecto decide cuáles son obligatorias. |
| **Preguntas** | Cuando un agente tiene confianza baja, encuentra una contradicción, dos jueces no coinciden, falta información o agotó sus reintentos de autocorrección. |
| **Revisión por excepción** | Solo lo riesgoso: reglas P0, confianza baja y una muestra aleatoria configurable (10% por defecto) del resto. |

**Niveles de autonomía por proyecto:**

- **Guiado:** todas las compuertas y todas las reglas P0 pasan por una persona (recomendado para el primer
  proyecto con un cliente).
- **Balanceado (por defecto):** C1–C4, preguntas y revisión por excepción.
- **Autónomo:** solo C1 y C4 más las preguntas escaladas.

**Formato de una pregunta (tarjeta de decisión):**

- Pregunta, contexto y **evidencia** (líneas de código, documento, caso de prueba, regla).
- Motivo (confianza baja, contradicción, jueces en desacuerdo, falta información) e **impacto** (alto/bajo).
- **Combobox con la respuesta recomendada preseleccionada**, su justificación y nivel de confianza, más las
  alternativas y la opción **"Otra respuesta…"** para que la persona escriba la suya.
- Qué elementos afecta (reglas, pantallas, contratos, tests).
- Comentario opcional para el equipo o el auditor.
- **"Aceptar las recomendaciones de bajo impacto"** en bloque; las de impacto alto siempre requieren respuesta
  individual.

**Comportamiento:**

- Mientras una pregunta espera, los agentes **siguen con todo lo que no depende de ella** (el grafo conoce las
  dependencias); la plataforma no se detiene entera.
- Cada respuesta queda como **decisión trazable** en la spec (quién, cuándo, qué opción, si fue la recomendada)
  y reanuda solo los elementos afectados.
- Las preguntas se responden desde el proyecto (Especificación → Preguntas) o desde **Mis tareas**, donde se
  reúnen las de todos los proyectos.

**Límites de ejecución:** toda ejecución tiene presupuesto de tokens/costo, límite de iteraciones y timeout.

### 10.5 Integración con el Claude Agent SDK (opcional)

Para tareas intensivas en código (generar y corregir un módulo dentro del sandbox), un nodo LangGraph puede
delegar en el Claude Agent SDK. La delegación respeta el mismo presupuesto, las mismas herramientas
permitidas y el mismo registro de consumo.

---

## 11. Verificación, validación y autocorrección

### 11.1 Patrón hacer → verificar → corregir (en cada fase)

1. **Trabajador** produce el artefacto.
2. **Verificación determinista primero:** compila, pasan los tests, cumple el esquema, la cita `archivo:línea`
   existe, cumple las fitness functions.
3. **Verificación con modelo después:** revisor con **otro contexto y, preferiblemente, otro modelo**.
4. **Corrector** recibe el error concreto y reintenta.
5. **Límites:** máximo de iteraciones y presupuesto; al agotarse, **escala a humano** con el diagnóstico.
   Nunca avanza "a medias".

### 11.2 Verificación de la extracción de reglas

- Cada regla cita `archivo:línea`; un árbitro verifica que la cita existe y respalda la regla.
- Para reglas P0, panel de dos jueces.
- Huecos de cobertura (shards no intentados, agentes caídos, archivos sin leer) se listan y pueden relanzarse.

### 11.3 Verificación independiente del resultado (veredicto por módulo)

Calculado **por código** con reglas fijas. Chequeos:

| # | Chequeo | Exige |
|---|---|---|
| 1 | Tests corrieron | Ejecución limpia (sin cachés); conteos leídos de JUnit XML o log crudo, nunca tipeados |
| 2 | Reglas trazadas | Cada regla (P0 obligatoriamente; P1/P2 según política del proyecto) respaldada por un test que corrió y pasó |
| 3 | Mismo comportamiento | Casos de desarrollo re-juzgados byte a byte con máscaras declaradas y tolerancias acotadas con motivo |
| 4 | Inputs frescos | ≥ 10 inputs nuevos corridos en ambos lados sin diferencias (si el legacy corre) |
| 5 | Canario | Un cambio deliberado de una línea pone tests en rojo (evidencia en archivo) |
| 6 | Fuente intacta | Ningún archivo del legacy modificado desde el preflight |

- **PROVEN:** todos pasan. **NOT PROVEN:** alguno falla. **PARTLY PROVEN:** nada falló pero algo no pudo comprobarse.
- Cada veredicto lista **lo que no prueba** (muestras, máscaras, tolerancias, reglas no extraídas…).
- **PROVEN es evidencia, no aprobación:** una persona firma el sign-off.
- El validador es **independiente** del constructor: rehace el trabajo, no confía en sus notas.

### 11.4 Validación en el Flujo 2

Aceptación desde Gherkin, contract tests contra OpenAPI, fidelidad visual contra el frame aprobado,
accesibilidad y seguridad automáticas, canario.

### 11.5 Completitud estructural (consultas al grafo)

- Párrafos clasificados como lógica de negocio sin regla asociada.
- Reglas sin caso de prueba que pase.
- Campos de salida del legacy sin `MAPS_TO` en el destino.
- Pantallas aprobadas sin componente implementado.
- Preguntas abiertas.

Se muestran como semáforo de completitud por dominio junto al veredicto de equivalencia.

### 11.6 Trazabilidad verificada

Cada vínculo del grafo (regla → línea legacy, regla → método destino, test → regla) se verifica
(la línea existe, el método existe, el test pasó). El visor de trazabilidad solo muestra vínculos
verificados o los marca como no verificados.

---

## 12. Configuración de modelos de IA

### 12.1 Conexiones (por tenant)

| Proveedor | Autenticación recomendada | Particularidades |
|---|---|---|
| **Azure AI Foundry** | Entra ID (service principal / managed identity) | Uso por *deployments* con nombre del cliente; el catálogo lee sus deployments |
| **AWS Bedrock** | Rol IAM asumido entre cuentas (sin llaves estáticas) | Habilitación por cuenta y región; inference profiles; IDs versionados |
| **OpenAI API** | API key en Vault/KMS | Alias y snapshots fechados |
| **OpenRouter** | API key en Vault/KMS | Agregador con API compatible con OpenAI. **Primer proveedor implementado** (M1, D-28). Se usa en desarrollo, pruebas o producción según lo configure cada cliente. Fija proveedor de enrutamiento y versión del modelo; devuelve el costo por llamada ([ADR-0005](adr/0005-openrouter-proveedor-inicial.md)) |
| **Otros** (Anthropic API, Vertex AI, modelos locales vía vLLM) | Según proveedor | Mismo modelo de datos |

Cada conexión tiene "probar conexión" (credenciales, permisos, modelos disponibles).

### 12.2 Catálogo: familia → modelo/versión → oferta

- **Oferta** = modelo × proveedor × región, con ID exacto, precio, ventana de contexto, capacidades y estado.
- Sincronización con cada proveedor; el administrador completa lo que la API no informa.
- **Siempre versiones fijas**, nunca alias tipo "latest" (reproducibilidad).
- La UI bloquea asignaciones incompatibles (visión, tool calling, salida estructurada, contexto).

### 12.3 Perfiles de modelo

Perfil = oferta + parámetros:

- **Esfuerzo normalizado** (bajo / medio / alto / máximo), traducido al parámetro real de cada modelo
  (nivel de esfuerzo o de razonamiento, o presupuesto de tokens de razonamiento, según el proveedor).
  La tabla de equivalencias es por oferta, editable por el administrador, y la UI muestra el parámetro real.
  **Mantener esta tabla con la documentación vigente de cada proveedor.**
- Tokens máximos de salida, temperatura (si aplica), timeout, reintentos.
- Cadena de **fallback** (p. ej. misma familia en otro proveedor).

### 12.4 Cascada de configuración

`Global → Tenant → Proyecto → Fase → Rol de agente`. Cada nivel hereda y puede sobrescribir.

### 12.5 Matriz de asignación del proyecto

Tabla fase × rol → perfil + fallback. Un proyecto puede combinar varios proveedores (p. ej. Bedrock para
generación, Foundry para extracción, OpenAI para visión). El verificador debe usar un modelo distinto
del generador cuando la política lo exija.

### 12.6 Políticas por tenant

Modelos y regiones permitidos, proveedores prohibidos, límites de uso, retención de prompts y respuestas.
Para agregadores (OpenRouter), además: proveedores de destino permitidos y exigencia de retención cero (ZDR) y
de no entrenamiento; un tenant puede prohibir el agregador por completo.

### 12.7 Implementación

- LangChain (`init_chat_model` o equivalente) como capa de abstracción de proveedores.
- Un único **gateway de modelos** interno por el que pasan todas las llamadas: aplica política, perfil,
  fallback, presupuesto y registro de consumo. Ningún agente llama a un proveedor directamente.

---

## 13. Consumo de tokens y costos

### 13.1 Captura

Cada llamada registra (desde el gateway de modelos, vía callback):

- Tokens de entrada, salida, razonamiento, caché (lectura y escritura).
- Etiquetas: tenant, proyecto, ejecución, fase, agente, iteración de autocorrección, perfil, oferta, conexión.
- Latencia, reintentos, si fue fallback.

### 13.2 Libro de consumo

- Tabla **append-only** en PostgreSQL: fuente de verdad para costos (Langfuse se usa para depurar).
- Cada registro guarda la **versión de precio** aplicada.

### 13.3 Tabla de precios

Versionada por oferta (mismo modelo, precio distinto por proveedor), por tipo de token y con fecha de
vigencia. La mantiene el administrador. Un cambio de tarifa no reescribe costos pasados.

### 13.4 Reconciliación (opcional)

Comparar el costo calculado con la facturación real del proveedor (AWS Cost Explorer, Azure Cost Management)
usando etiquetas. En OpenRouter, con el costo que el proveedor informa en cada respuesta.

### 13.5 Vistas

- **Por cliente:** total, por proyecto, por proveedor, tendencia mensual.
- **Por proyecto:** por fase, agente, modelo; costo de la autocorrección (reintentos).
- **Economía unitaria:** costo por mil líneas, por regla extraída, por módulo verificado.
- **Presupuestos y alertas:** al 80% se avisa; al 100% la ejecución se pausa en su checkpoint.
- **Proyección:** costo estimado para terminar, según el costo real de lo ya hecho.
- Permisos separados para "ver consumo (tokens)" y "ver costo (dinero)".

---

## 14. Multi-cliente, multi-proyecto y modelos de despliegue

### 14.1 Jerarquía

`Plataforma → Cliente (tenant) → Proyecto → Ejecución`. Todo registro lleva `tenant_id`; en una instancia
dedicada simplemente hay un solo tenant (una sola base de código).

### 14.2 Aislamiento

| Recurso | Aislamiento |
|---|---|
| PostgreSQL | `tenant_id` en todas las tablas + **Row-Level Security** |
| Neo4j | Base por tenant (Enterprise) o particionado estricto con capa de acceso única |
| Object storage | Bucket o prefijo por tenant, **llave KMS por tenant** |
| Sandbox | Contenedor efímero por trabajo, nunca compartido entre tenants |
| Credenciales de modelos | Por tenant (BYOK) |

### 14.3 Modelos de despliegue (todos soportados por diseño)

| Modelo | Plano de control | Plano de datos |
|---|---|---|
| **SaaS compartido** | NexTI | NexTI, multi-tenant |
| **SaaS dedicado** | NexTI | NexTI, uno por cliente |
| **Nube del cliente** | NexTI | Cuenta AWS/Azure/GCP del cliente; conexión saliente hacia el control; solo envía estado y métricas, nunca código |
| **On-prem / air-gapped** | Cliente | Cliente; actualizaciones por paquete firmado y licencia offline; modelos locales |

- **Plano de control:** consola, tenants, licencias, catálogo, versiones de prompts/skills, telemetría agregada.
- **Plano de datos:** workers, sandbox, Neo4j, storage, Postgres del proyecto, conexión a modelos.

### 14.4 Empaquetado

- Contenedores + **Helm** (EKS, AKS, GKE, OpenShift, on-prem).
- Módulo **Terraform/OpenTofu por nube** para la infraestructura base.
- **Perfiles de despliegue** que eligen servicios gestionados (RDS / Azure Database / Cloud SQL / Postgres propio).
- Versionado semántico de plataforma, adaptadores, packs y prompts; cada ejecución registra versiones exactas.
- Licenciamiento: verificación online (SaaS) o archivo firmado (air-gapped).

### 14.5 Orden de construcción

Diseñar para los cuatro desde el inicio; construir y operar primero **SaaS compartido** y **plano de datos
en la nube del cliente**. Dedicado sale de lo anterior. Air-gapped cuando haya un cliente concreto.

---

## 15. Seguridad

Estándar objetivo: **OWASP ASVS nivel 2** como mínimo (nivel 3 en autenticación, autorización y manejo
de datos del cliente).

### 15.1 Identidad y módulo de autenticación

La plataforma soporta **dos métodos de inicio de sesión**, habilitables por tenant (uno o ambos):

1. **SSO** con el proveedor de identidad del cliente: OIDC o SAML 2.0 (Microsoft Entra ID, Okta,
   Google Workspace, Keycloak u otro compatible). El MFA lo exige el proveedor.
2. **Cuentas de la plataforma** (módulo de autenticación propio): correo + contraseña, **siempre con MFA**.

**Flujo de login**

- **Home-realm discovery:** el usuario escribe su correo; si el dominio pertenece a un tenant con SSO,
  se le redirige a su proveedor. Si el tenant marca "solo SSO", el acceso con contraseña queda deshabilitado
  para ese dominio.
- Botones directos de SSO (Entra ID, Okta, Google) y "otro SSO" por dominio de empresa.
- Contraseña → segundo factor: TOTP (app de autenticación), **passkeys (WebAuthn)** o códigos de
  recuperación. SMS solo como último recurso (desaconsejado por robo de SIM).
- **Invitación:** el usuario invitado activa su cuenta, define su contraseña según la política y configura MFA.
- **Recuperación de contraseña:** enlace de un solo uso con vencimiento (30 min); el mensaje es el mismo
  exista o no la cuenta (evita enumeración). Las cuentas SSO se recuperan en su proveedor.

**Configuración por tenant (Administración → Autenticación)**

- Métodos habilitados (SSO, cuentas propias; al menos uno obligatorio).
- Proveedores de identidad: protocolo, issuer/metadata URL, client ID, secreto (en Vault), dominios,
  modo (solo SSO u opcional), **mapeo de grupos a roles**, aprovisionamiento **JIT** y **SCIM**.
- Política de contraseñas: longitud mínima (12 por defecto), complejidad, historial, vencimiento
  (0 = sin vencimiento forzado cuando hay MFA), rechazo de contraseñas filtradas.
- Política de MFA: obligatoria para todos; métodos permitidos.
- Sesiones: inactividad (30 min por defecto), duración máxima (12 h), sesiones simultáneas.
- Bloqueo: intentos fallidos (5) y duración (15 min).

**Cuenta del usuario (Cuenta y seguridad):** perfil e idioma, cambio de contraseña (solo cuentas propias),
métodos MFA y passkeys, regeneración de códigos de recuperación, sesiones activas con revocación.

**Implementación: Keycloak (decisión D-19)**

El módulo de autenticación se implementa con **Keycloak** como proveedor de identidad y broker. La
plataforma **no almacena contraseñas ni secretos de MFA**: todo eso vive en Keycloak.

- **Rol de Keycloak:**
  - IdP de las cuentas propias (usuario/contraseña, TOTP, passkeys/WebAuthn, códigos de recuperación,
    políticas de contraseña, bloqueo por fuerza bruta, verificación de correo, recuperación de contraseña).
  - **Broker** hacia los IdP de los clientes (Entra ID, Okta, Google, cualquier OIDC/SAML), con mapeo
    de grupos/claims a roles y aprovisionamiento JIT.
  - Emisión de tokens OIDC hacia el BFF de la plataforma.
- **Multi-tenant (decisión D-20, ADR-0002):** en SaaS compartido, **un realm de la plataforma con una
  Organization por tenant** (IdP y dominios asociados a cada organización, lo que da el home-realm discovery
  por dominio de correo; un usuario de NexTI tiene una sola cuenta con membresía en varias organizaciones).
  En despliegues dedicados, en la nube del cliente u on-prem, **una instancia (o un realm) de Keycloak por
  despliegue**; para la plataforma sigue siendo un tenant, sin cambios de código. Si un cliente del SaaS
  exige una política que Keycloak solo permite por realm (p. ej. contraseñas o duración de sesión), pasa a
  realm dedicado. Versión de Keycloak con Organizations estable (26 o posterior), **fijada**; la validación
  con tests se hace en M0b.
- **Flujo:** la web → BFF (FastAPI) → Keycloak (Authorization Code + PKCE). El BFF guarda los tokens del
  lado servidor y entrega al navegador solo una cookie de sesión `httpOnly`, `Secure`, `SameSite`.
  Protección CSRF. Sesiones cortas, rotación y revocación inmediata (logout propaga a Keycloak).
- **Pantallas de login:** las páginas de Keycloak (login, MFA, recuperación, activación) se personalizan
  con un **tema propio construido con Keycloakify** a partir del diseño del prototipo (`apps/web`), con
  los mismos catálogos en inglés (por defecto) y español. La pantalla "email first" puede quedar en la web
  y redirigir a Keycloak con `login_hint` e `kc_idp_hint` según el dominio.
- **Administración:** la pestaña Administración → Autenticación de la plataforma configura Keycloak a través
  de su **Admin REST API** (con una cuenta de servicio de mínimo privilegio). La consola de Keycloak no se
  expone a los clientes.
- **Autorización:** Keycloak autentica; **OpenFGA autoriza** (roles y permisos de la sección 16). Los grupos
  del IdP del cliente se traducen a roles de la plataforma al iniciar sesión.
- **SCIM:** Keycloak no trae SCIM nativo; se agrega con una extensión o un endpoint SCIM en la plataforma
  que sincroniza hacia Keycloak (decidir en el hito correspondiente).
- **Auditoría:** los eventos de Keycloak (login, fallo, bloqueo, cambios de MFA, admin events) se envían
  al log de auditoría de la plataforma.
- **Operación:** Keycloak en alta disponibilidad con su propia base PostgreSQL, actualizaciones de
  seguridad al día, tema y configuración versionados como código (exportación de realm / Terraform).

**Implantación por etapas (decisión D-27, ADR-0004)**

La autenticación va con Keycloak **desde el primer hito**, pero con lo mínimo; lo empresarial se agrega al
final como configuración, sin cambiar la API ni las pantallas.

| Etapa | Qué incluye | Qué no incluye todavía |
|---|---|---|
| **M0** | Keycloak en Docker Compose con un realm importado al arrancar (`infra/keycloak/`), **cuentas locales con usuario y contraseña guardadas en Keycloak**, BFF con cookie `httpOnly`, logout, sesión y CSRF. En la base de la plataforma: usuarios (enlazados a Keycloak por `sub`), tenants, membresías, roles, permisos, invitaciones y rol por proyecto, sincronizados con OpenFGA | SSO con IdP externos, MFA obligatoria, Organizations, home-realm discovery, tema Keycloakify, políticas por tenant vía Admin REST API |
| **M0b** | SSO con **Microsoft Entra ID** (y Okta, Google o cualquier OIDC/SAML) como IdP de Keycloak, mapeo de grupos a roles y JIT, **MFA** (TOTP, passkeys, recuperación), **Organizations por tenant**, home-realm discovery y "solo SSO", tema Keycloakify desde las pantallas del prototipo, configuración por tenant desde Administración | — |

- **Lo que no cambia en ninguna etapa:** la plataforma **no guarda contraseñas ni secretos de MFA** (viven en
  Keycloak), el navegador no recibe tokens y OpenFGA autoriza. Pasar de M0 a M0b es agregar proveedores y
  políticas en Keycloak.
- **Modo `dev-auth` (solo desarrollo y tests):** para trabajar rápido, la API puede iniciar sesión eligiendo
  un **usuario sembrado**, sin contraseña, y emite la misma cookie de sesión que el BFF. Solo existe si
  `APP_ENV=development` o `test`; la API **se niega a arrancar** con `dev-auth` activo en cualquier otro
  entorno (test automatizado) y cada inicio de sesión por esta vía queda en la auditoría marcado como
  `dev-auth`. No reemplaza a Keycloak en los tests de aceptación de M0.
- **Módulo de usuarios y permisos propio:** es parte de la plataforma desde M0 (entidades de 19.4 y
  sección 16): la pantalla Administración gestiona usuarios, invitaciones, roles, la matriz de permisos y el
  rol por proyecto; las credenciales se gestionan en Keycloak.

### 15.2 Perímetro

WAF, rate limiting por usuario/tenant/IP, protección de bots, TLS 1.2+ (preferido 1.3), HSTS, CSP estricta,
listas de IPs permitidas por tenant (opcional).

### 15.3 Datos

- Cifrado en tránsito y en reposo con **llave por tenant**.
- Secretos en Vault/KMS, nunca en la base ni en el repositorio.
- Retención configurable y **borrado verificable** al cerrar un proyecto.
- Compromiso de no uso de datos para entrenamiento (configuración del proveedor + contrato).
- Enmascarado de credenciales detectadas en el código subido antes de enviarlo a un modelo.

### 15.4 El código subido es input hostil

- Validación de archivos: zip bombs, path traversal, enlaces simbólicos, tamaños, tipos.
- Escaneo de malware.
- **Prompt injection:** el código se trata como dato, delimitado y marcado como no confiable; los agentes
  de análisis **no tienen** herramientas de red, credenciales ni escritura fuera de su workspace.
- Nada producido por un modelo se ejecuta fuera del sandbox.

### 15.5 Sandbox

Contenedores efímeros por trabajo, **sin salida a red** por defecto, límites de CPU/memoria/tiempo,
sistema de archivos aislado, aislamiento reforzado (gVisor o Firecracker). Runners Windows para .NET Framework.

### 15.6 Auditoría

Log **inmutable** (append-only, con encadenamiento de hashes) de quién hizo qué, cuándo, con qué versión de
agente, skill, modelo y precio. Exportable para auditorías regulatorias.

### 15.7 Ciclo de desarrollo seguro

SAST, análisis de dependencias (SCA), secret scanning y DAST en CI; imágenes firmadas; SBOM;
pentest periódico.

---

## 16. RBAC y autorización

### 16.1 Roles por alcance

| Alcance | Roles |
|---|---|
| **Plataforma** | Superadministrador (NexTI), Operador de soporte |
| **Tenant** | Administrador del cliente, Auditor (solo lectura de toda la evidencia), Finanzas (costos) |
| **Proyecto** | Dueño, Arquitecto, Analista/Delivery, Revisor de negocio / PO, Desarrollador, Observador/Cliente |

### 16.2 Permisos granulares (ejemplos)

`proyecto.crear`, `proyecto.configurar`, `insumo.subir`, `pipeline.ejecutar`, `compuerta.c1.aprobar`,
`compuerta.c2.aprobar`, `compuerta.c3.aprobar`, `signoff.firmar`, `codigo.ver`, `codigo.descargar`,
`codigo.push`, `pregunta.responder`, `historia.editar`, `plan.editar`, `prototipo.comentar`, `prototipo.editar`, `modelos.configurar`, `integraciones.gestionar`, `identidad.gestionar`, `consumo.ver`, `costo.ver`, `agentes.seleccionar`, `skills.seleccionar`,
`skills.publicar`, `usuarios.gestionar`, `auditoria.ver`.

Los roles son **paquetes configurables** de permisos.

### 16.3 Reglas

- **Segregación de funciones:** quien lanzó una generación no puede aprobar su propia compuerta.
- Herencia: administrador del tenant ⇒ puede todo en los proyectos de su tenant (salvo firmar sign-offs
  si no es miembro con ese permiso).
- Toda decisión de autorización se registra en la auditoría cuando es una denegación o una acción sensible.

### 16.4 Implementación

**OpenFGA** (modelo de relaciones estilo Zanzibar) para la jerarquía plataforma → tenant → proyecto
(decisión D-15, ADR-0001). Casbin quedó descartado: los permisos son relaciones (rol por proyecto, herencia
del administrador del tenant, segregación de funciones) y la plataforma necesita preguntar tanto "¿puede X
hacer Y sobre Z?" como "¿qué proyectos puede ver X?" (listados, buscador, panel de actividad).

- **Fuente de verdad de los roles:** PostgreSQL (`membership`, `project_member`, `role`, `role_permission`).
  Un único módulo de la API escribe la tabla y la relación en OpenFGA en la misma operación (patrón outbox) y
  un job de reconciliación corrige diferencias.
- **Modelo versionado** en `infra/openfga/` con tests del modelo (casos permitido/denegado) en CI.
- Cada endpoint consulta OpenFGA con el usuario y el tenant de la sesión; las denegaciones van a la auditoría.

---

## 17. Administración y configurabilidad

Todo lo siguiente es configurable desde la UI por el rol correspondiente, con validación y vista previa:

- Tenants: alta, modelo de despliegue, licencia, cuotas.
- Usuarios, invitaciones, roles y permisos.
- Identidad: SSO/OIDC por tenant, MFA, políticas de sesión.
- Seguridad y datos: retención, borrado, llaves, IPs permitidas.
- Catálogo: adaptadores y packs habilitados por tenant, matriz de compatibilidad, niveles.
- Plantillas de pipeline: fases activas, compuertas obligatorias, límites de autocorrección.
- Agentes y skills: catálogo, versiones, publicación con aprobación y evaluación.
- Configuración IA: conexiones, catálogo, perfiles, matriz por defecto, precios, políticas, presupuestos.
- Prompts y constitución del cliente: versionados, con historial.
- Integraciones: GitHub, GitLab, Azure DevOps, Jira, Figma. Las conexiones se crean **por tenant**; cada
  proyecto elige cuál usa (Jira/Azure DevOps en el asistente o en la pestaña Backlog, sección 7.6).

**Defaults sólidos:** plantillas "estándar banco" e "interno ágil". La configuración avanzada queda detrás
de permisos de administrador. Toda configuración es versionada y auditable.

---

## 18. Frontend: mapa de la aplicación

### 18.1 Estructura

- **Barra superior:** selector de cliente (usuarios NexTI), buscador global, notificaciones, perfil.
- **Menú lateral** (filtrado por permisos):

```
├─ Dashboard
├─ Proyectos
│   └─ Espacio de trabajo del proyecto
├─ Mis tareas / Aprobaciones
├─ Consumo y costos
├─ Configuración IA
├─ Catálogo (agentes, skills, adaptadores, packs, plantillas, design systems)
├─ Administración
└─ Operación de plataforma (solo NexTI)
```

### 18.2 Dashboard (por perfil)

- **Ejecutivo del cliente:** avance por proyecto, reglas migradas y verificadas, veredictos, riesgos,
  costo vs presupuesto.
- **Delivery NexTI:** ejecuciones en curso, fases trabadas, compuertas pendientes, escalamientos, consumo del día.
- **Administrador:** usuarios activos, uso por cliente, alertas de presupuesto y seguridad, estado de conexiones.

### 18.3 Proyectos

**Listado** con flujo, origen → destino, fase actual, veredicto, costo; filtros.

**Asistente de creación:**

1. Datos básicos, flujo e idioma de los artefactos (inglés por defecto).
2. Origen (tecnologías; zip/Git o insumos documentales). Incluye además:
   - **Referencias de UI:** capturas de pantalla (con miniaturas), links de Figma (validados:
     `figma.com/file|design|proto`) y links de prototipos.
   - **Seguimiento del trabajo:** vincular el proyecto a Jira o Azure DevOps (conexión del tenant + proyecto)
     y activar la creación automática del backlog al aprobar C1 (sección 7.6).
3. Destino y arquitectura (matriz de compatibilidad con avisos).
4. **Equipo de agentes** (cards; recomendados con motivo; reemplazar/quitar/agregar).
5. **Skills** (agrupadas por agente; recomendadas; conflictos y faltantes).
6. **Modelos** (heredar o personalizar la matriz fase × rol).
7. Plantilla de pipeline y presupuesto.
8. Equipo humano y roles.
9. Revisión (resumen, costo estimado, advertencias) → Crear.

**Espacio de trabajo (pestañas):**

| Pestaña | Contenido |
|---|---|
| Resumen | Pipeline visual, próximos pasos, riesgos, veredicto, costo |
| Insumos | Código, repos, documentos, Figma, capturas, links de prototipos, Jira/Azure DevOps, con versiones |
| Inventario / Mapa | **Grafo interactivo** del legacy (sección 5.2.1): recorrido de flujos de negocio paso a paso, foco por regla, filtros de relaciones, filtro de huérfanos y aislados, color por dominio o estado, buscador, zoom y arrastre, detalle del nodo, **análisis de impacto** y acceso directo a la comparación |
| Especificación | Subvistas: reglas, **historias de usuario** (editar, crear, dividir, fusionar, descartar; cobertura; versiones), **plan de migración** por olas (sugerido y editable, con validación de dependencias), pantallas (campos, validaciones, acciones, estados), contratos y **preguntas** (tarjetas de decisión, sección 10.4) |
| Diseño UI | Design system, prototipos navegables con comentarios, legacy ↔ prototipo, **referencias** (capturas, Figma, prototipos) y **chat de cambios** con el agente UX/UI designer (7.4) |
| Arquitectura | Bounded contexts, OpenAPI, ADR, fitness functions |
| Código | Navegador de archivos, descarga o push según permisos |
| Origen ↔ destino | Comparación por regla o por programa: **código legacy y código destino lado a lado** con las líneas relacionadas resaltadas, la regla con su estado de verificación y el **comportamiento legacy vs nuevo** (golden master e inputs frescos, con las diferencias marcadas) |
| Validación | Tests, golden master con diffs, inputs frescos, canario, veredicto, sign-off |
| Backlog | Conexión Jira/Azure DevOps del proyecto, mapeo de tipos, reglas de automatización, árbol feature → historia → tarea → bug con estado y sincronización, y **ciclo del bug** paso a paso (7.6) |
| Ejecuciones | Historial y **vista en vivo de los agentes** (fase, subagentes, verificaciones, autocorrecciones) |
| Costos | Consumo por fase, agente, modelo vs presupuesto |
| Actividad | Auditoría del proyecto |
| Configuración | Equipo, agentes, skills, modelos, pipeline, presupuesto, integraciones |

### 18.4 Otras secciones

- **Autenticación (pantallas públicas):** login con home-realm discovery y SSO, segundo factor (MFA),
  recuperación de contraseña y activación de invitación (sección 15.1).
- **Cuenta y seguridad:** perfil, idioma, contraseña, MFA/passkeys y sesiones activas.

- **Mis tareas:** dos vistas: **Preguntas para mí** (tarjetas de decisión de todos los proyectos, respondibles ahí mismo) y **Aprobaciones y revisiones** (compuertas, **revisión de historias y plan de migración**, prototipos, sign-offs).
- **Consumo y costos:** consolidado, economía unitaria, presupuestos, proyecciones, exportación.
- **Configuración IA:** conexiones, catálogo, perfiles, matriz por defecto, precios, políticas, prompts,
  evaluaciones por modelo.
- **Catálogo:** agentes (cards), skills, adaptadores, packs, compatibilidad, plantillas, design systems.
- **Administración:** tenants, usuarios, roles, identidad, seguridad, integraciones, auditoría global.
- **Operación de plataforma:** salud de workers y colas, sandbox, errores, versiones por instancia.

### 18.5 Transversales

Tiempo real (SSE/WebSocket), inglés nativo con cambio a español (18.6), tema claro/oscuro, WCAG 2.1 AA, todo enlazable por URL,
estados vacíos, de carga y de error en todas las vistas, y el **panel flotante de actividad de agentes** (18.8).

### 18.6 Idioma: inglés nativo, español como alternativa

**Toda la plataforma es nativamente en inglés.** El español es una traducción completa y se activa por
elección del usuario.

**Interfaz**

- Los textos fuente de la UI se escriben en **inglés**; las claves y el catálogo base son `en`.
  El catálogo `es` es una traducción de ese base.
- Idioma por defecto: inglés. Orden de resolución:
  preferencia del usuario → idioma por defecto del tenant → inglés.
  (No se usa el idioma del navegador para cambiar el default, salvo que el tenant lo habilite.)
- Selector de idioma en el perfil y en la barra superior; el cambio es inmediato y persiste.
- Fechas, números y monedas con formato del locale (`en-US` / `es-*`), independiente del idioma de los datos.
- Correos, notificaciones y exportaciones (PDF, informes) en el idioma del destinatario.
- Mensajes de error de la API: códigos estables + texto en inglés; la web los muestra traducidos por código.
- CI falla si una clave existe en `en` y falta en `es` (o al revés).

**Artefactos generados (spec, reglas, documentación, informes de verificación)**

- Idioma configurable **por proyecto**, con **inglés por defecto**; opción de generarlos en español
  (útil para bancos cuyo negocio revisa en español).
- El idioma elegido se pasa a los agentes como parámetro del proyecto; los prompts de sistema y las skills
  se mantienen en **inglés** (idioma base) y piden la salida en el idioma del proyecto.
- Identificadores técnicos (`RULE-NNN`, veredictos `PROVEN / PARTLY PROVEN / NOT PROVEN`, nombres de
  fases en la API) son iguales en ambos idiomas; en la UI se muestran con su etiqueta traducida.
- El código generado usa identificadores en inglés; los comentarios siguen el idioma del proyecto.

**Catálogo y contenido administrable**

- Agentes, skills, plantillas de pipeline y design systems: nombre y descripción en inglés, con traducción
  opcional al español (si falta, se muestra el inglés).

### 18.7 Prototipo navegable (`apps/web`)

Existe un prototipo de todas las pantallas de esta sección en `apps/web`, construido con el stack
definitivo del frontend (React + TypeScript + Vite + Tailwind + TanStack Router + i18next), en inglés
nativo con cambio a español y tema claro/oscuro.

- Los datos vienen de `apps/web/src/mocks/` (tipos en `types.ts`, datos en `data.ts`). Los tipos reflejan
  las entidades de la sección 19.4 para que los mocks se reemplacen por llamadas a la API con la misma forma.
- La sesión es simulada (`src/lib/session.ts`); en el sistema real la emite el BFF en una cookie `httpOnly`.
- La recomendación de agentes y skills y las reglas de compatibilidad son deterministas
  (`src/lib/recommend.ts`) y deben migrar al backend manteniendo el mismo comportamiento.
- Incluye los formularios de alta y edición (agentes, skills, conexiones IA, perfiles, precios, clientes,
  invitaciones, roles y matriz de permisos, proveedores de identidad, insumos), el buscador global, las
  notificaciones, el detalle de cada invocación de agente, el grafo interactivo con recorrido de flujos de
  negocio, foco por regla y filtro de huérfanos, la comparación origen ↔ destino y las tarjetas de decisión del
  human in the loop.
- También incluye las referencias de UI en el asistente, Insumos y Diseño UI, el chat de cambios al
  prototipo, la pestaña Backlog (Jira/Azure DevOps con ciclo de bugs), el panel flotante de actividad de
  agentes (18.8) y las historias de usuario con el plan de migración por olas (7.7; la validación del plan
  está en `src/lib/migrationPlan.ts` y la de los criterios Gherkin en `src/lib/gherkin.ts`, deterministas y
  con tests, y deben migrar al backend con el mismo comportamiento).
- **Componentes (D-14):** las primitivas del prototipo (`components/ui/primitives.tsx` y `overlay.tsx`) pasan a
  usar **shadcn/ui sobre Radix** por dentro (Dialog/Sheet para el `Drawer`, Select, Combobox, Tooltip, Toast,
  Tabs) **sin cambiar su API**, así las pantallas no se tocan. Se valida con tests de accesibilidad (axe).
- **Login (D-27):** en M0 las pantallas de login, MFA, recuperación e invitación del prototipo no se usan (el
  login es el de Keycloak con su tema base, o el selector de `dev-auth` en desarrollo); en M0b pasan a ser el
  tema Keycloakify.
- Capturas de referencia en `docs/prototipo/`.
- Cómo correrlo: ver `apps/web/README.md`.

### 18.8 Panel flotante de actividad de agentes

Panel tipo *copilot*, disponible en todas las pantallas autenticadas (D-23), que muestra en vivo lo que hacen
los agentes de los proyectos a los que el usuario tiene acceso.

- **Estados del panel:** minimizado (píldora con agentes en ejecución, errores y costo acumulado), abierto
  (ventana en la esquina inferior derecha) y maximizado (casi pantalla completa). Se minimiza, maximiza y
  restaura con un clic.
- **Orden:** el evento más reciente siempre arriba, ordenado por hora; una cabecera "Último" destaca el
  evento más nuevo.
- **Cada evento muestra:** nombre del agente, proyecto, fase, mensaje de lo que está haciendo ("en
  ejecución…"), **tiempo transcurrido** en vivo, **costo** y tokens, modelo y estado (en ejecución, correcto,
  fallido, esperando a una persona).
- **Filtros:** todos, en ejecución, fallidos, esperando, correctos.
- **Errores:** al expandir un evento fallido se ve el error y se puede **descargar el JSON completo**
  (evento, proyecto, ejecución, modelo, traza, entorno, fecha de exportación) para soporte o análisis. El JSON
  pasa por el mismo filtro de secretos que los logs: nunca incluye credenciales ni tokens.
- **Fuente de datos:** en el sistema real, el stream SSE de eventos de ejecución (19.5), filtrado por
  autorización (OpenFGA) en el servidor; el costo viene del libro de consumo del gateway.
- Los avisos (`toast`) se muestran abajo a la izquierda para no tapar el panel.

---

## 19. Arquitectura técnica, stack y estructura del repositorio

### 19.1 Componentes

```
React (web) ──HTTPS──> WAF / API Gateway
                            │
                  FastAPI (BFF + API) ── OIDC + OpenFGA
                            │
      ┌─────────────────────┼──────────────────────┐
  PostgreSQL        Cola (PostgreSQL,         Neo4j
                    Procrastinate)
  (app, RLS,                │                  Object storage (S3/MinIO)
   checkpoints,       Workers LangGraph        Vault / KMS
   libro consumo)           │
                      Gateway de modelos ── Proveedores (OpenRouter, Foundry, Bedrock, OpenAI…)
                            │
                      Sandbox de ejecución
                      Langfuse (trazas y evaluación)
```

### 19.2 Stack

| Capa | Tecnología |
|---|---|
| Frontend | React + TypeScript, Vite, TanStack Query y TanStack Router, Tailwind + **shadcn/ui sobre Radix** (D-14; se adoptan detrás de las primitivas del prototipo), grafo en SVG propio con d3-hierarchy (vista de círculos; evaluar Cytoscape.js o Sigma.js para grafos de miles de nodos), Monaco (código), i18next |
| Backend API | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic |
| Orquestación | LangGraph (checkpointer PostgreSQL), LangChain (abstracción de modelos y herramientas) |
| Trabajos | Workers Python con cola **Procrastinate sobre PostgreSQL** (D-13, ADR-0009) |
| Datos | PostgreSQL 16+, Neo4j 5, S3 / MinIO |
| Autorización | OpenFGA (D-15) |
| Identidad | **Keycloak** (IdP + broker SSO, Organizations por tenant, tema con Keycloakify; D-19, D-20); en dev, en Docker Compose con realm importado y cuentas locales (D-27) |
| Observabilidad | Langfuse (autoalojado), OpenTelemetry, logs estructurados |
| Sandbox | Docker (dev), gVisor/Firecracker (prod), runners Windows para .NET Framework |
| Parsers | Parsers propios/deterministas por origen; tree-sitter para nivel asistido |
| Infraestructura | Docker Compose (dev), Helm, Terraform/OpenTofu |
| Calidad | pytest, Vitest, Playwright, Ruff, mypy, ESLint, Prettier |

### 19.3 Estructura del repositorio (propuesta)

```
/
├─ CLAUDE.md                      # Instrucciones para Claude Code
├─ README.md
├─ docs/
│  ├─ ESPECIFICACION_PLATAFORMA.md
│  ├─ adr/                        # Decisiones de arquitectura (ADR-NNN)
│  └─ referencia/                 # Plantillas de spec de referencia (sin código de clientes)
├─ apps/
│  ├─ web/                        # React
│  ├─ api/                        # FastAPI (BFF + API)
│  └─ worker/                     # Workers LangGraph
├─ packages/                      # Python (workspace uv)
│  ├─ core/                       # Dominio compartido: tenants, proyectos, spec, tipos neutrales
│  ├─ graph/                      # Capa de acceso a Neo4j (única, con filtros de tenant)
│  ├─ model_gateway/              # Gateway de modelos, perfiles, esfuerzo, consumo
│  ├─ orchestration/              # Composición de grafos LangGraph, patrón hacer-verificar-corregir
│  ├─ agents/                     # Definiciones de agentes (fichas + prompts)
│  ├─ skills/                     # Skills (SKILL.md + recursos)
│  ├─ adapters/source/            # cobol, cics_bms, sybase, aspx
│  ├─ packs/target/               # spring_boot, dotnet, angular, react, postgres, ...
│  ├─ verification/               # compare, trace, proof pack, canario
│  └─ sandbox/                    # Cliente del sandbox
├─ infra/
│  ├─ docker-compose/             # Entorno local completo
│  ├─ helm/
│  └─ terraform/                  # aws, azure, gcp
└─ .github/workflows/             # CI
```

**Prohibido** en este repositorio: código de clientes (incluidas las aplicaciones de referencia),
credenciales, datos reales. Las aplicaciones de referencia viven en un almacenamiento separado con acceso
restringido.

### 19.4 Modelo de datos relacional (entidades principales)

- **Identidad y tenancy:** `tenant`, `app_user` (global, sin `tenant_id`, D-29), `membership`, `role` (por tenant,
  copia de los roles base), `permission` y `permission_scope` (catálogo), `role_permission`, `role_assignment`
  (rol de tenant o de proyecto; reemplaza a `project_member`), `invitation`, `platform_role_assignment`,
  `authz_outbox`, `keycloak_event_cursor`; más adelante `identity_provider`, `license`, `deployment`.
- **Proyectos:** `project`, `project_config` (versionada), `pipeline_template`, `input_artifact`
  (insumo, con hash y versión), `integration`.
- **Ejecución:** `run`, `phase_run`, `agent_invocation`, `gate`, `approval`, `question`, `verdict`,
  `evidence_file`, `activity_event` (eventos del panel de actividad, derivados de `agent_invocation`).
- **Seguimiento del trabajo:** `integration_connection` (por tenant: Jira o Azure DevOps),
  `project_tracker_link` (proyecto ↔ proyecto externo, mapeo de tipos, reglas de automatización),
  `work_item_link` (ítem de la plataforma ↔ clave externa, tipo, estado, última sincronización),
  `bug_loop_step` (pasos del ciclo de bug con agente y evidencia).
- **Historias y plan:** `feature`, `user_story` (estado, origen, prioridad, estimación, motivo de descarte,
  fuera de alcance, fusionada en), `story_version` (instantánea por versión, quién y qué cambió),
  `acceptance_criterion` (Gherkin, con el resultado de la validación y la versión del validador), `story_link` (HU ↔ regla, pantalla, contrato o nodo del grafo),
  `story_dependency` (dura o blanda, motivo, origen: grafo o persona), `story_suggestion`, `migration_plan`
  (versionado, sugerido o editado, aprobado en C1) y `migration_wave` (orden de HU por ola).
- **Catálogo:** `agent_definition`, `skill_definition` (versionadas), `project_agent`, `project_skill`,
  `source_adapter`, `target_pack`, `compatibility_rule`, `design_system`, `prototype`,
  `prototype_version` (versión generada por cada cambio), `prototype_chat_message`, `ui_reference`
  (captura, link de Figma o link de prototipo, como `input_artifact`).
- **IA:** `provider_connection`, `model_family`, `model_version`, `model_offering`, `model_profile`,
  `effort_mapping`, `model_assignment`, `price_version`, `model_policy`.
- **Consumo:** `usage_ledger` (append-only), `budget`, `budget_alert`.
- **Auditoría:** `audit_log` (append-only, hash encadenado).

Todas las tablas de negocio llevan `tenant_id` con RLS; las excepciones (identidad global, catálogo, roles de
plataforma) están en [ADR-0006](adr/0006-identidad-global-sin-tenant-id.md).

### 19.5 API (esbozo)

- REST versionada: `/api/v1/...` con recursos anidados por tenant y proyecto
  (p. ej. `/api/v1/projects/{id}/runs`, `/api/v1/projects/{id}/spec/rules`).
- El tenant se deriva de la sesión (no se confía en un parámetro del cliente).
- Eventos en tiempo real: `GET /api/v1/runs/{id}/events` (SSE) y `GET /api/v1/activity/events` (SSE del
  panel de actividad, filtrado por autorización).
- Backlog: `/api/v1/projects/{id}/tracker` (vínculo y reglas), `/api/v1/projects/{id}/work-items`,
  `POST /api/v1/projects/{id}/work-items:sync`; prototipos: `/api/v1/projects/{id}/prototypes/{screen}/chat`.
- Historias y plan: `/api/v1/projects/{id}/stories` (CRUD, `:split`, `:merge`, `:discard`, `:restore`,
  `/versions`), `/api/v1/projects/{id}/migration-plan` (`GET` sugerido y actual, `PUT` validado en el
  servidor, `:reset`); la aprobación va con la compuerta C1.
- OpenAPI generado por FastAPI; cliente TypeScript generado desde él para el frontend.
- Paginación, filtros y errores con formato uniforme (RFC 9457 Problem Details).

---

## 20. Roadmap por hitos

Cada hito termina con: código en la rama, tests pasando en CI, documentación actualizada y una demo.

### M0 — Fundaciones

Plan detallado (archivos, tablas, endpoints, tests y pasos): `docs/planes/M0-fundaciones.md`.

- Monorepo (uv workspace + pnpm), CI (lint, tipos, tests, SAST, SCA, secret scanning).
- Docker Compose local: PostgreSQL, Neo4j, Redis, MinIO, Keycloak, OpenFGA, Langfuse.
- FastAPI con OIDC (patrón BFF, cookies), sesión, CSRF.
- Tenants, usuarios, membresías, RLS, OpenFGA con roles base.
- **Módulo de usuarios y permisos:** usuarios (enlazados a Keycloak por `sub`), invitaciones, roles, matriz
  de permisos y rol por proyecto, con sus pantallas de Administración; sincronización con OpenFGA (outbox +
  reconciliación) y modelo de OpenFGA versionado con tests (D-15, sección 16.4).
- Audit log append-only.
- Autenticación **mínima con Keycloak** (D-27, sección 15.1): realm importado al arrancar, cuentas locales con
  usuario y contraseña en Keycloak, BFF con cookie `httpOnly`, logout, sesión y CSRF; modo `dev-auth` solo en
  desarrollo y tests. SSO, MFA, Organizations y Keycloakify quedan para **M0b**.
- Web: conectar el prototipo de `apps/web` (sección 18.7) a la API real: login, layout, menú por permisos, tema.
- Primitivas de UI sobre shadcn/ui + Radix sin cambiar su API (D-14), con tests de accesibilidad (axe).
- i18n: inglés como idioma fuente y por defecto; catálogo en español; selector de idioma (18.6).

**Aceptación:** un usuario de un tenant no puede ver datos de otro (test automatizado a nivel API y SQL);
se inicia sesión con una cuenta local de Keycloak y se cierra sesión; ningún token llega al navegador; la
plataforma no guarda contraseñas (test sobre el esquema: no hay columnas de contraseña ni secretos); la API no
arranca con `dev-auth` fuera de desarrollo/test; cada endpoint tiene test de autorización permitido y
denegado contra OpenFGA; un cambio de rol en la base se refleja en OpenFGA (y la reconciliación corrige una
diferencia forzada); toda acción sensible (incluidos los eventos de Keycloak) queda en la auditoría.
La web arranca en inglés; al cambiar a español no queda ningún texto sin traducir (test automatizado
que compara las claves de ambos catálogos); la preferencia persiste entre sesiones; las primitivas migradas
pasan los tests de accesibilidad.

### M1 — Configuración IA y consumo

Plan detallado y cierre (criterios con sus tests): `docs/planes/M1-configuracion-ia.md`.

- Conexión **OpenRouter** (primer proveedor, D-28) con "probar conexión" y secreto en Vault (dev: equivalente local),
  proveedor de enrutamiento fijado y políticas de ZDR y proveedores permitidos por tenant. Foundry, Bedrock y
  OpenAI se agregan después sobre el mismo modelo de datos (cuando un cliente lo requiera, antes de M9).
- Catálogo familia → versión → oferta con sincronización; capacidades.
- Perfiles con esfuerzo normalizado y tabla de equivalencias; fallback.
- Cascada de configuración y matriz fase × rol.
- Gateway de modelos único; libro de consumo; precios versionados; presupuestos y alertas.
- Pantallas de Configuración IA y Consumo y costos.

**Aceptación:** una llamada de prueba por OpenRouter queda registrada con tokens y costo correctos (y el costo
coincide con el que informa OpenRouter); una política de tenant que prohíbe OpenRouter o exige ZDR se respeta;
superar un presupuesto pausa la ejecución; un agente no puede llamar a un proveedor sin pasar por el gateway.

### M2 — Proyectos e insumos

Plan detallado: `docs/planes/M2-proyectos-insumos.md`.

- CRUD de proyectos, asistente de creación (sin ejecutar agentes aún), con referencias de UI (capturas,
  links de Figma y de prototipos) desde el paso 2 (7.1).
- Subida de insumos a object storage (validación, malware, hash, versión); conexión Git.
- Catálogo de agentes y skills (fichas, cards), recomendación determinista, validación de composición.
- Matriz de compatibilidad y plantillas de pipeline.

**Aceptación:** crear un proyecto CICS+BMS → Spring Boot + Angular + PostgreSQL + AWS propone el equipo y
las skills esperados; no se puede quitar un agente de Control; subir un zip con path traversal es rechazado;
un link de Figma que no es `figma.com/file|design|proto` se rechaza y una captura pasa por las mismas validaciones.

### M3 — Motor de orquestación

Plan detallado: `docs/planes/M3-motor-orquestacion.md`.

- Composición dinámica de grafos LangGraph desde el proyecto; checkpointer PostgreSQL.
- Workers y cola; interrupts para compuertas; reanudación tras fallo.
- Patrón hacer → verificar → corregir con límites y escalamiento.
- Sandbox (Docker en dev) sin red.
- SSE de progreso; pestaña Ejecuciones en vivo; bandeja Mis tareas.
- Human in the loop (10.4): niveles de autonomía por proyecto y tarjetas de decisión con respuesta recomendada,
  alternativas y respuesta propia.
- Panel flotante de actividad de agentes (18.8) conectado al SSE, con descarga del JSON de error.

**Aceptación:** matar un worker a mitad de una fase y reanudar sin perder trabajo; una compuerta detiene el
flujo hasta la aprobación de un usuario con el permiso; la autocorrección respeta el máximo de iteraciones;
el panel de actividad solo muestra eventos de proyectos autorizados y el JSON descargado no contiene secretos.

### M4 — Primer vertical completo: Sybase SP → destino + PostgreSQL

Plan detallado: `docs/planes/M4-vertical-sybase.md`.

- Adaptador Sybase (inventario, tipos neutrales, extracción de reglas).
- Spec y revisión (C1), diseño (C3), generación por capas en el pack elegido (Java Spring Boot o .NET 10,
  ver decisión D-06).
- **Historias de usuario y plan de migración** (7.7): HU derivadas de la spec; editar, crear, dividir,
  fusionar, descartar y restaurar con versiones y auditoría; cobertura; **validación Gherkin** de los criterios
  de aceptación (en vivo y en el servidor); plan por olas sugerido desde el grafo, editable y validado por
  código; aprobación conjunta en C1.
- Comparación origen ↔ destino lado a lado por regla, con comportamiento legacy vs nuevo.
- Golden master con Sybase ASE en contenedor y PostgreSQL; `verification` (compare, trace, proof pack, canario).
- Pestañas Especificación, Validación y Trazabilidad (versión inicial).

**Aceptación:** con la aplicación de referencia Sybase se obtiene un veredicto calculado por código; se miden
omisiones, alucinaciones y errores de precisión contra la spec de referencia. Además: mover una HU antes de
una dependencia dura se rechaza (también si se llama a la API directamente); una dependencia blanda se
permite con aviso; descartar una HU que deja reglas sin cubrir lo muestra en la cobertura; C1 no se aprueba
con HU con preguntas abiertas, sin criterios, con Gherkin inválido o con dependencias duras rotas; guardar
un escenario sin `When`, con pasos fuera de orden o con un `<placeholder>` que no está en `Examples` se
rechaza también por API (en inglés y en español); todo cambio de HU o del plan
queda versionado y auditado; un usuario sin permiso no puede editar HU ni el plan (test permitido y denegado).

### M5 — BMS → pantallas y prototipos

- Parser BMS determinista → spec de pantalla.
- Design system base NexTI y propuesta de prototipos navegables; comentarios e iteración (C2).
- Chat de cambios al prototipo con versiones (7.4); referencias de UI (capturas, Figma, prototipos).
- Vista legacy ↔ prototipo.

**Aceptación:** todos los campos de los mapas de la aplicación de referencia aparecen en la spec de pantalla
con posición, longitud y atributos correctos.

### M6 — COBOL CICS

- Adaptador COBOL/CICS (inventario, clasificación, slicing, extracción).
- Transacción → Programa → Mapa en el grafo; importación de trazas para golden master.
- Visualización completa del grafo (5.2.1): vistas de círculos y capas, recorrido de flujos de negocio, foco
  por regla, filtros de relaciones, huérfanos y aislados, detalle del nodo e impacto.
- Visor de trazabilidad Legacy | Regla | Destino completo.

**Aceptación:** medición contra la spec de referencia CICS; veredicto máximo PARTLY PROVEN si no hay ejecución.

### M6b — Packs de frontend: React y Angular

- Packs de destino de frontend (8.4): React y Angular, con el design system aprobado en C2 (tokens y
  componentes) y un cliente tipado generado del OpenAPI del backend (determinista).
- Generación de las pantallas desde las specs de pantalla y los prototipos aprobados; validación y navegación
  según la spec; accesibilidad (WCAG AA) automática.
- Build y tests (unitarios y e2e) en el sandbox web; se integran a la verificación independiente.
- El proyecto elige el frontend en el asistente; sin pack, la generación del frontend espera (como en D-06).

**Aceptación:** con la aplicación ficticia (SP de M4 + mapas de M5), el frontend React y el Angular compilan,
pasan sus tests y cubren todos los campos, validaciones y acciones de las specs de pantalla; axe sin
violaciones graves.

### M6c — Pack .NET 10 + SQL Server

- Pack de backend .NET 10 (ASP.NET Core, hexagonal como el de Spring Boot) y persistencia SQL Server, con el
  mismo contrato de diseño (C3), generación por capas, sandbox propio sin red y harness de equivalencia.
- El mismo diseño y golden master de M4 generan un destino .NET y se verifican con los seis chequeos (11.3).

**Aceptación:** la aplicación ficticia de M4 migrada a .NET 10 + SQL Server obtiene un veredicto calculado por
código con el mismo golden master que Spring Boot.

### M7 — Flujo 2 completo

- Ingesta de documentos, HU, Figma (API), capturas (visión) y links de prototipos, desde el asistente y después.
- Normalización, consolidación, detección de contradicciones y huecos, preguntas.
- Historias de usuario y plan de incrementos (7.7) con HU que vienen de documentos, Figma y Jira/Azure DevOps;
  sus criterios se normalizan a Gherkin y pasan la misma validación (una HU importada inválida bloquea C1).
- Generación con contratos primero; validación de aceptación, contract tests y fidelidad visual.

**Aceptación:** con un set de HU + Figma de ejemplo se genera y valida una funcionalidad de punta a punta,
con cada elemento trazado a su insumo.

### M7b — Integración Jira / Azure DevOps

- Conexión por tenant en Administración (Vault), vínculo por proyecto en el asistente y en la pestaña Backlog.
- Generación del backlog desde las **HU aprobadas** en C1 (7.7), ordenado por ola; los cambios posteriores
  entran como cambio de alcance; marcado automático de terminado con evidencia.
- Ciclo de bugs: tester crea el bug, developer propone la corrección en el sandbox, re-test y cierre, dentro
  del nivel de autonomía y del máximo de iteraciones (7.6).

**Aceptación:** con un proyecto Jira y uno de Azure DevOps de prueba, aprobar C1 crea la jerarquía esperada sin
duplicados al re-sincronizar; un test fallido crea un bug y el ciclo termina en revisión humana; un usuario de
otro tenant no ve ni usa la conexión; toda escritura externa queda auditada.

### M8 — ASPX / .NET Framework

- Adaptador ASPX (markup → pantallas, code-behind → reglas y contratos).
- Opción *uplift* a .NET 10 vs reescritura.
- Runner Windows en el sandbox.

### M8b — Packs Oracle y nube (AWS, Azure)

- Persistencia Oracle en los packs de backend existentes (Spring Boot y .NET), con su sandbox de verificación.
- Eje de despliegue (8.4): IaC con Terraform/OpenTofu para AWS y Azure en contenedores, con mapeo de conceptos
  legacy a servicios gestionados; validación estática del IaC en el sandbox (sin credenciales de nube).

**Aceptación:** la aplicación ficticia genera y verifica su destino con Oracle, y su IaC para AWS y Azure pasa
la validación y las fitness functions del pack.

### M0b — Identidad empresarial (SSO, MFA, Organizations)

Se hace **después de los hitos funcionales y antes de M9** (o antes, si un cliente lo necesita para un piloto);
es configuración de Keycloak más pantallas, sin cambios en la API de negocio (D-27).

- SSO con **Microsoft Entra ID** y otros IdP OIDC/SAML (Okta, Google) como proveedores de Keycloak; mapeo de
  grupos a roles y aprovisionamiento JIT.
- MFA obligatoria para cuentas propias (TOTP, passkeys/WebAuthn, códigos de recuperación), políticas de
  contraseña, bloqueo, recuperación de contraseña e invitaciones con activación.
- **Organizations por tenant** en un realm (D-20), home-realm discovery y modo "solo SSO"; realm dedicado para
  despliegues dedicados.
- Tema **Keycloakify** construido desde las pantallas del prototipo (en y es).
- Administración → Autenticación configura Keycloak vía Admin REST API con cuenta de servicio de mínimo privilegio.
- Eventos de Keycloak a la auditoría.

**Aceptación:** login con SSO (un segundo Keycloak o un IdP de prueba como proveedor externo, y Entra ID en un
tenant de prueba) y con cuenta propia + MFA; un dominio con "solo SSO" no puede entrar con contraseña; el
token trae la Organization y de ella sale el `tenant_id`; un usuario de NexTI con membresía en dos
organizaciones solo ve los datos del tenant activo; los grupos del IdP se traducen a los roles esperados;
ningún token llega al navegador y la plataforma sigue sin guardar contraseñas.

### M9 — Endurecimiento y despliegue

- Helm, Terraform por nube, perfiles de despliegue; plano de datos en la nube del cliente.
- Revisión ASVS, DAST, pentest; SBOM e imágenes firmadas.
- Operación de plataforma.

### Posterior

Flujo 3, Flujo 4, olas 2 y 3 de certificación, air-gapped, exportación a Figma.

---

## 21. Aplicaciones de referencia y evaluación

### 21.1 Disponibles

1. COBOL CICS con mapas BMS.
2. Stored procedure en Sybase.
3. Aplicación ASPX.
4. (Público) AWS CardDemo para COBOL batch/CICS/BMS.

### 21.2 Qué se prepara por aplicación

- Código completo (anonimizado, sin credenciales, con permiso contractual para I+D).
- **Spec de referencia escrita a mano por un experto, antes de ver cualquier extracción** (evita sesgo).
- Datos de prueba y salidas esperadas (golden master).
- Entorno de ejecución, si es posible.

### 21.3 Plantilla de spec de referencia

- Reglas (20–30 principales): enunciado, condición con valores concretos, resultado, ubicación aproximada,
  prioridad.
- Pantallas: campo, tipo, longitud, obligatorio, validación, mensaje, navegación.
- Datos: tablas/archivos principales y campos de precisión especial.
- Rarezas conocidas (comportamientos a preservar o defectos conocidos).
- Casos de prueba: 5–10 con entrada y salida esperada.

### 21.4 Métricas

- **Omisiones:** reglas de la referencia no encontradas (la métrica más grave).
- **Alucinaciones:** reglas encontradas que no existen.
- **Errores de precisión:** regla encontrada con valores distintos.
- Pantallas y campos mapeados correctamente.
- Veredicto de equivalencia, costo y tiempo por aplicación.

Las métricas se ejecutan por cada versión de adaptador, skill, agente y modelo, y se publican en el catálogo.

### 21.5 Orden

Sybase SP (M4) → BMS (M5) → CICS (M6) → ASPX (M8).

---

## 22. Decisiones registradas y pendientes

### 22.1 Registradas

| Id | Decisión |
|---|---|
| D-01 | Metodología SDD como columna vertebral; strangler fig solo para convivencia en el Flujo 1 |
| D-02 | v1 incluye Flujo 1 y Flujo 2; flujos 3 y 4 posteriores pero preparados |
| D-03 | Frontend React; backend Python con LangGraph y LangChain |
| D-04 | Grafo en Neo4j; transaccional en PostgreSQL; código fuera del grafo |
| D-05 | Hexagonal por dentro en todo destino generado |
| D-07 | Veredicto calculado por código; agentes de Control obligatorios |
| D-08 | Soporte de todos los modelos de despliegue por diseño |
| D-09 | Multi-proveedor de modelos con gateway único y libro de consumo propio |
| D-10 | Agentes y skills seleccionables con recomendación determinista |
| D-21 | Human in the loop por compuertas, preguntas con respuesta recomendada y revisión por excepción; tres niveles de autonomía por proyecto (sección 10.4) |
| D-19 | Autenticación con **Keycloak** (IdP + broker SSO, Organizations por tenant, tema Keycloakify); la plataforma no guarda credenciales; OpenFGA autoriza |
| D-22 | Jira y Azure DevOps: **conexión por tenant** (Administración), **vínculo por proyecto** (asistente o pestaña Backlog); los agentes crean y cierran ítems, el tester crea bugs y el developer los corrige dentro de los límites de autonomía e iteraciones (7.6) |
| D-23 | Panel flotante de actividad de agentes en toda la app: minimizable/maximizable, evento más reciente arriba, agente, tiempo y costo por evento, JSON completo descargable en errores (18.8) |
| D-24 | Referencias de UI (capturas, Figma, prototipos) cargables desde la creación del proyecto y después; chat con el agente UX/UI designer para pedir cambios al prototipo, con versiones y sin aprobar por sí solo (7.1, 7.4) |
| D-25 | Historias de usuario visibles y editables antes de migrar (crear, editar, dividir, fusionar, descartar con motivo) y plan de migración por olas **sugerido por el sistema y modificable por las personas**, validado por código contra las dependencias del grafo; ambos se aprueban en C1 y después todo cambio es cambio de alcance (7.7) |
| D-26 | Criterios de aceptación de las HU en Gherkin **validados por código** (Given/When/Then en orden, un comportamiento por escenario, esquemas con ejemplos, sin duplicados; inglés y español); un criterio inválido impide guardar y bloquea C1 (7.7) |
| D-14 | Componentes UI: **shadcn/ui sobre Radix**, adoptados detrás de las primitivas del prototipo sin cambiar su API; accesibilidad validada con axe ([ADR-0003](adr/0003-componentes-ui-shadcn-radix.md)) |
| D-15 | Autorización con **OpenFGA** (relaciones estilo Zanzibar); roles en PostgreSQL como fuente de verdad, sincronizados por outbox con reconciliación; Casbin descartado ([ADR-0001](adr/0001-autorizacion-openfga.md)) |
| D-20 | Keycloak: **un realm con una Organization por tenant** en el SaaS compartido; realm o instancia dedicada en despliegues dedicados o si un cliente exige políticas por realm; versión fijada 26+ ([ADR-0002](adr/0002-keycloak-organizations-por-tenant.md)) |
| D-27 | Autenticación **por etapas**: Keycloak mínimo desde M0 (cuentas locales en Keycloak, BFF, `dev-auth` solo en desarrollo) y SSO/MFA/Organizations/Keycloakify en **M0b**; la plataforma nunca guarda contraseñas ([ADR-0004](adr/0004-autenticacion-por-etapas.md)) |
| D-18 | Producto nativamente en inglés (UI, prompts, skills, catálogo); español como traducción completa; idioma de artefactos configurable por proyecto (inglés por defecto) |
| D-13 | Cola de trabajos con **Procrastinate sobre PostgreSQL**: ejecución y trabajo en la misma transacción, latidos para reintentar el trabajo de un worker caído y reanudación desde el checkpoint de LangGraph; cola y checkpointer sin `tenant_id` y solo con referencias ([ADR-0009](adr/0009-cola-procrastinate-postgresql.md)) |
| D-36 | Pack .NET 10 + SQL Server sobre un **contrato común de packs de backend**: la orquestación elige el pack por `target.backend`; diseño, resultado de build y vistas de equivalencia en paquetes comunes; ASP.NET Core hexagonal con ADO.NET, xUnit, harness de equivalencia en C# y canario; sandbox con SQL Server 2025 preinicializado y NuGet sin red ([ADR-0017](adr/0017-pack-dotnet-y-contrato-de-packs-de-backend.md)) |
| D-37 | Flujo 2: cada insumo (documento, Figma) se convierte en un texto con líneas citables, como el código del Flujo 1; integraciones del tenant con el token en OpenBao; veredicto del Flujo 2 calculado por código con tests, criterios Gherkin cubiertos por tests con su id, contratos, canario, preguntas cerradas y trazado a insumos ([ADR-0018](adr/0018-flujo-2-insumos-citables-y-veredicto.md)) |
| D-38 | Backlog en Jira y Azure DevOps: un contrato de rastreador con clientes REST, escrituras idempotentes por `work_item_link` (y etiqueta para recuperar tras una caída), creación al aprobar C1 por ola, terminado con evidencia del veredicto, bug escrito por código desde la evidencia y corrección del developer como borrador que espera revisión humana ([ADR-0019](adr/0019-backlog-jira-azure-devops.md)) |
| D-39 | ASPX / .NET Framework: adaptador determinista (markup → pantallas con validadores; code-behind → slices por manejador de evento y tablas del SQL), golden master desde trazas grabadas con techo PARTLY PROVEN mientras no haya runner Windows, y evaluación de uplift frente a reescritura por archivo ([ADR-0020](adr/0020-aspx-parser-trazas-y-uplift.md)) |
| D-40 | Oracle Database Free dentro del sandbox Java para verificar el destino Oracle (red interna por corrida y raíz escribible solo para imágenes de motores de base de datos, el resto del contrato intacto); IaC OpenTofu para AWS y Azure generado desde el diseño y validado sin credenciales con fitness functions calculadas por código ([ADR-0021](adr/0021-oracle-e-iac-aws-azure.md)) |
| D-41 | Identidad empresarial: una Organization de Keycloak por tenant reconciliada por la Admin REST API; proveedores OIDC/SAML por tenant vinculados a su Organization, con home-realm discovery en el BFF, "solo SSO" comprobado en el callback, JIT y grupos del IdP a roles de OpenFGA; MFA por nivel de autenticación (LoA) pedido por el BFF cuando el tenant la exige; tema Keycloakify en una imagen propia ([ADR-0022](adr/0022-identidad-empresarial-organizations-sso-mfa.md)) |
| D-42 | M9 se divide en **M9a** (endurecimiento y entrega del proyecto: informe calculado por código con secretos, dependencias en OSV, reglas estáticas y tiempos de tests; release con plan de corte strangler fig y push a una rama nueva del repositorio del cliente con `codigo.push`) y **M9b** (despliegue de la plataforma: contenedores, Helm, OpenTofu por nube, perfiles, SBOM, imágenes firmadas, DAST y operación) ([ADR-0023](adr/0023-endurecimiento-entrega-y-division-de-m9.md)) |
| D-35 | Packs de frontend React y Angular con un **contrato OpenAPI 3.1 derivado por código del diseño (C3)** y un cliente tipado generado de él; imagen de sandbox de frontend sin red (TypeScript, React, Angular AOT, jsdom, axe); un **arnés de pantallas** de la plataforma verifica campos, validaciones, acciones, navegación y accesibilidad; el agente solo escribe las pantallas; veredicto propio del frontend ([ADR-0016](adr/0016-packs-de-frontend-react-y-angular.md)) |
| D-34 | COBOL/CICS con **parser propio y determinista** de un subconjunto documentado (formato fijo, `COPY`, `DATA DIVISION`, párrafos, `EXEC CICS`/`EXEC SQL`, CSD); lo no reconocido es un problema del inventario. El golden master de CICS sale de **trazas importadas** con el mismo contrato que un runner; sin ejecución del legacy el veredicto no pasa de PARTLY PROVEN ([ADR-0015](adr/0015-cobol-cics-parser-y-trazas.md)) |
| D-33 | Los packs de destino de la Ola 1 tienen hitos propios: **M6b** frontend React y Angular, **M6c** .NET 10 + SQL Server, **M8b** Oracle y nube AWS/Azure (IaC); cualquier origen soportado puede ir a cualquier pack disponible ([ADR-0014](adr/0014-hitos-de-packs-de-destino.md)) |
| D-32 | Prototipos en **React real**: el agente escribe TSX solo con React y el design system NexTI, un validador por código lo revisa, se compila en un sandbox web sin red y se muestra en un **iframe aislado** (sin mismo origen) servido con CSP estricta ([ADR-0013](adr/0013-prototipos-react-en-iframe-aislado.md)) |
| D-31 | Insumos validados por un único módulo (`packages/ingest`) antes de guardarse: tipo por contenido, tamaños, zip seguro (path traversal, enlaces, bombs), cabecera de imágenes, secretos contados y sha256; **malware con ClamAV** en Compose, CI y despliegue, con falla cerrada si no responde; síncrono en la API hasta que existan workers ([ADR-0008](adr/0008-validacion-de-insumos-clamav.md)) |
| D-30 | Secretos con la **API de Vault** (KV v2) a través de un único módulo del gateway; **OpenBao** en desarrollo y CI, Vault u OpenBao en producción; la base solo guarda la ruta ([ADR-0007](adr/0007-almacen-de-secretos-openbao.md)) |
| D-29 | Identidad global: `app_user`, el catálogo de permisos y los roles de plataforma sin `tenant_id`, con visibilidad por RLS y membresía; toda otra tabla de negocio lleva `tenant_id` con RLS forzado ([ADR-0006](adr/0006-identidad-global-sin-tenant-id.md)) |
| D-06 | El primer vertical Sybase migra a **Java Spring Boot + PostgreSQL**, el primer pack que se construye; el destino no es fijo: el asistente siempre pide los cinco ejes y un backend sin pack espera en la generación, nunca genera otro lenguaje; las aplicaciones de referencia de clientes viven en un kit local fuera del repo y el CI usa respuestas de modelos grabadas ([ADR-0010](adr/0010-primer-pack-java-spring-boot.md), [ADR-0011](adr/0011-kit-de-referencia-fuera-del-repo.md), [ADR-0012](adr/0012-respuestas-grabadas-y-evaluacion-a-demanda.md)) |
| D-28 | **OpenRouter** como primer proveedor de modelos (M1): conexión por tenant usable en desarrollo, pruebas o producción según decida cada cliente, con proveedor de enrutamiento y versión fijados y políticas de ZDR y proveedores permitidos; Foundry, Bedrock y OpenAI después sobre el mismo modelo de datos ([ADR-0005](adr/0005-openrouter-proveedor-inicial.md)) |

### 22.2 Pendientes

| Id | Pregunta |
|---|---|
| D-11 | ¿NexTI solo informa el consumo de IA o también lo factura (con margen) cuando la cuenta es de NexTI? |
| D-12 | Neo4j Community (particionado por etiqueta) vs Enterprise (base por tenant) |
| D-16 | Modelo de licenciamiento (por proyecto, por líneas, por tenant) |
| D-17 | Primer cliente para despliegue en nube propia: ¿AWS o Azure? |

Las decisiones nuevas se agregan como ADR en `docs/adr/` y se reflejan aquí.

---

## 23. Requisitos no funcionales

- **Disponibilidad (SaaS):** objetivo 99,5% (v1).
- **Rendimiento API:** p95 < 300 ms para lecturas simples; las operaciones largas son asíncronas.
- **Escala:** proyectos con decenas de miles de campos y miles de programas; fan-out con concurrencia configurable.
- **Durabilidad:** ninguna ejecución pierde trabajo completado ante la caída de un worker.
- **Reproducibilidad:** toda ejecución registra versiones de agentes, skills, prompts, modelos (ID exacto),
  precios y plataforma.
- **Observabilidad:** trazas por ejecución, fase y llamada; métricas de costo y latencia.
- **Accesibilidad:** WCAG 2.1 AA.
- **Internacionalización:** inglés nativo (por defecto) y español; preparada para agregar más idiomas sin cambiar código.
- **Portabilidad:** Kubernetes en cualquier nube u on-prem.

---

## 24. Glosario

| Término | Significado |
|---|---|
| **SDD** | Spec-Driven Development: se especifica, se genera desde la spec y se verifica contra ella |
| **Spec** | Especificación estructurada (reglas, pantallas, contratos, entidades, RNF, casos) |
| **Slice** | Porción de código que influye en un dato de salida (program slicing) |
| **Golden master** | Salidas del legacy congeladas como oráculo |
| **Canario** | Cambio deliberado para comprobar que los tests detectan errores |
| **Compuerta (C1–C4)** | Aprobación humana entre fases |
| **Veredicto** | PROVEN / PARTLY PROVEN / NOT PROVEN, calculado por código |
| **Adaptador de origen** | Módulo que lleva una tecnología legacy a la spec |
| **Pack de destino** | Módulo que genera un stack destino desde la spec |
| **Oferta de modelo** | Modelo × proveedor × región |
| **Perfil de modelo** | Oferta + parámetros (esfuerzo, límites, fallback) |
| **Tenant** | Cliente de la plataforma |
| **Plano de control / de datos** | Gestión central / donde se procesa el código del cliente |
| **Strangler fig** | Reemplazo progresivo del legacy por dominios |
| **ACL** | Anti-corruption layer entre modelo viejo y nuevo |
| **IV&V** | Verificación y validación independiente (Flujo 4) |

---

## 25. Anexo: reutilización del plugin `code-modernization` de Anthropic

Plugin oficial de Claude Code (licencia **Apache 2.0**), repositorio `anthropics/claude-plugins-official`,
carpeta `plugins/code-modernization`.

### 25.1 Qué reutilizar (respetando la licencia y la atribución)

- **Prompts de agentes** como punto de partida (legacy-analyst, business-rules-extractor, architecture-critic,
  security-auditor, test-engineer, scaffolder, …), adaptados a COBOL/Sybase/.NET bancario y a la generación de artefactos en inglés o español.
- **Scripts de verificación** como referencia de diseño para `packages/verification`:
  `compare.py` (comparación byte a byte con máscaras y tolerancias), `trace_rules.py` (regla → test),
  `proof_pack.py` (veredicto por reglas fijas).
- **Formatos de artefactos:** rule cards Given/When/Then, `topology.json`, `EQUIVALENCE.json`,
  `VERIFICATION.md/json`.

### 25.2 Qué aporta la plataforma y el plugin no tiene

Grafo persistente, multiusuario y multi-cliente, parsers deterministas, semántica de datos bancaria,
migración de datos, orquestación con presupuesto y reanudación gestionada, visor de trazabilidad,
completitud estructural, validación de reglas más allá de P0, y producto bilingüe (inglés nativo, español).

### 25.3 Lecciones de diseño adoptadas

- El estado vive en archivos/datos, no en la conversación.
- El validador es independiente y rehace el trabajo.
- Los conteos se leen de archivos del runner, nunca se tipean.
- El código analizado es input no confiable.
- El veredicto dice explícitamente lo que no prueba.
