# Plataforma de Modernización y Construcción Asistida por IA — Especificación

> **Propósito de este documento.** Es la especificación maestra del producto. Sirve para que el equipo y
> Claude Code (en VS Code) construyan la plataforma por hitos. Cada hito de la sección 20 tiene entregables
> y criterios de aceptación verificables. Si algo del código contradice este documento, se corrige el
> código o se actualiza el documento de forma explícita (con una decisión registrada en la sección 22).

- **Producto:** plataforma web multi-cliente para modernizar aplicaciones legacy y construir funcionalidades
  nuevas a partir de documentación, con agentes de IA verificados.
- **Dueño:** NexTI Business Solutions.
- **Estado:** especificación inicial (v0.1).
- **Idioma de trabajo:** español (la plataforma debe soportar también inglés).

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
| **Pregunta abierta** | id, texto, elementos afectados, responsable, estado, respuesta |

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
- Orden de migración: ordenamiento topológico con peso por complejidad.
- Completitud (ver 11.5).

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
| 6 | **Revisión de reglas** | Negocio revisa, responde preguntas, corrige | Reglas aprobadas | **C1: spec aprobada** |
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
- Nada de UI: la plataforma **propone** design system y prototipos (7.4).

### 7.2 Fases

| # | Fase | Qué hace | Compuerta |
|---|---|---|---|
| 1 | **Ingesta** | Cada insumo con su lector; versión y hash de cada insumo | — |
| 2 | **Normalización** | Insumo → elementos de la spec (capacidades, HU normalizadas con Gherkin, pantallas, reglas, contratos, entidades, RNF) con origen | — |
| 3 | **Consolidación** | Cruce HU ↔ pantallas ↔ entidades; detección de **contradicciones** y **huecos** (reglas deterministas sobre el grafo + agente) → preguntas | — |
| 4 | **Revisión de spec** | PO responde preguntas y aprueba | **C1** |
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

### 7.5 Definición de "completo" en el Flujo 2

- Todo criterio de aceptación aprobado tiene un test que pasó.
- Todo frame/prototipo aprobado tiene su pantalla implementada.
- Todo campo tiene validación definida y probada.
- Todo endpoint del contrato está implementado y cubierto.
- No quedan preguntas abiertas.

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

### 10.4 Autonomía

- Los agentes son autónomos **dentro de una fase**.
- Entre fases hay **compuertas humanas** configurables por plantilla de pipeline (p. ej. "estándar banco"
  exige C1–C4; "interno ágil" puede omitir C2).
- Toda ejecución tiene presupuesto de tokens/costo, límite de iteraciones y timeout.

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
usando etiquetas.

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

### 15.1 Identidad

- OIDC con SSO del cliente (Entra ID, Okta, Keycloak); **MFA obligatorio**.
- **Patrón BFF:** el token nunca vive en el navegador; sesión en cookie `httpOnly`, `Secure`, `SameSite`.
- Sesiones cortas, rotación y revocación inmediata. Protección CSRF.

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
`codigo.push`, `modelos.configurar`, `consumo.ver`, `costo.ver`, `agentes.seleccionar`, `skills.seleccionar`,
`skills.publicar`, `usuarios.gestionar`, `auditoria.ver`.

Los roles son **paquetes configurables** de permisos.

### 16.3 Reglas

- **Segregación de funciones:** quien lanzó una generación no puede aprobar su propia compuerta.
- Herencia: administrador del tenant ⇒ puede todo en los proyectos de su tenant (salvo firmar sign-offs
  si no es miembro con ese permiso).
- Toda decisión de autorización se registra en la auditoría cuando es una denegación o una acción sensible.

### 16.4 Implementación

**OpenFGA** (modelo de relaciones estilo Zanzibar) para la jerarquía plataforma → tenant → proyecto.
Alternativa a evaluar: Casbin. Decisión en la sección 22.

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
- Integraciones: GitHub, GitLab, Azure DevOps, Jira, Figma.

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

1. Datos básicos y flujo.
2. Origen (tecnologías; zip/Git o insumos documentales).
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
| Insumos | Código, repos, documentos, Figma, capturas, con versiones |
| Inventario / Mapa | Grafo del legacy coloreado por dominio o estado; consultas de impacto |
| Especificación | Reglas, tablas de decisión, pantallas, contratos, dominio, preguntas abiertas |
| Diseño UI | Design system, prototipos navegables con comentarios, legacy ↔ prototipo |
| Arquitectura | Bounded contexts, OpenAPI, ADR, fitness functions |
| Código | Navegador de archivos, descarga o push según permisos |
| Trazabilidad | Visor **Legacy \| Regla \| Destino**, navegable en ambos sentidos (a detallar) |
| Validación | Tests, golden master con diffs, inputs frescos, canario, veredicto, sign-off |
| Ejecuciones | Historial y **vista en vivo de los agentes** (fase, subagentes, verificaciones, autocorrecciones) |
| Costos | Consumo por fase, agente, modelo vs presupuesto |
| Actividad | Auditoría del proyecto |
| Configuración | Equipo, agentes, skills, modelos, pipeline, presupuesto, integraciones |

### 18.4 Otras secciones

- **Mis tareas / Aprobaciones:** bandeja transversal (specs, prototipos, preguntas, escalamientos, sign-offs).
- **Consumo y costos:** consolidado, economía unitaria, presupuestos, proyecciones, exportación.
- **Configuración IA:** conexiones, catálogo, perfiles, matriz por defecto, precios, políticas, prompts,
  evaluaciones por modelo.
- **Catálogo:** agentes (cards), skills, adaptadores, packs, compatibilidad, plantillas, design systems.
- **Administración:** tenants, usuarios, roles, identidad, seguridad, integraciones, auditoría global.
- **Operación de plataforma:** salud de workers y colas, sandbox, errores, versiones por instancia.

### 18.5 Transversales

Tiempo real (SSE/WebSocket), i18n español/inglés, tema claro/oscuro, WCAG 2.1 AA, todo enlazable por URL,
estados vacíos, de carga y de error en todas las vistas.

---

## 19. Arquitectura técnica, stack y estructura del repositorio

### 19.1 Componentes

```
React (web) ──HTTPS──> WAF / API Gateway
                            │
                  FastAPI (BFF + API) ── OIDC + OpenFGA
                            │
      ┌─────────────────────┼──────────────────────┐
  PostgreSQL           Cola (Redis)            Neo4j
  (app, RLS,                │                  Object storage (S3/MinIO)
   checkpoints,       Workers LangGraph        Vault / KMS
   libro consumo)           │
                      Gateway de modelos ── Proveedores (Foundry, Bedrock, OpenAI…)
                            │
                      Sandbox de ejecución
                      Langfuse (trazas y evaluación)
```

### 19.2 Stack

| Capa | Tecnología |
|---|---|
| Frontend | React + TypeScript, Vite, TanStack Query y TanStack Router, Tailwind + shadcn/ui (a confirmar), Cytoscape.js o Sigma.js (grafo), Monaco (código), i18next |
| Backend API | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic |
| Orquestación | LangGraph (checkpointer PostgreSQL), LangChain (abstracción de modelos y herramientas) |
| Trabajos | Workers Python con cola sobre Redis (Celery o alternativa; decisión en la sección 22) |
| Datos | PostgreSQL 16+, Neo4j 5, S3 / MinIO |
| Autorización | OpenFGA |
| Identidad (dev) | Keycloak como IdP OIDC local |
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

- **Identidad y tenancy:** `tenant`, `user`, `membership`, `role`, `permission`, `role_permission`,
  `project_member`, `identity_provider`, `license`, `deployment`.
- **Proyectos:** `project`, `project_config` (versionada), `pipeline_template`, `input_artifact`
  (insumo, con hash y versión), `integration`.
- **Ejecución:** `run`, `phase_run`, `agent_invocation`, `gate`, `approval`, `question`, `verdict`,
  `evidence_file`.
- **Catálogo:** `agent_definition`, `skill_definition` (versionadas), `project_agent`, `project_skill`,
  `source_adapter`, `target_pack`, `compatibility_rule`, `design_system`, `prototype`.
- **IA:** `provider_connection`, `model_family`, `model_version`, `model_offering`, `model_profile`,
  `effort_mapping`, `model_assignment`, `price_version`, `model_policy`.
- **Consumo:** `usage_ledger` (append-only), `budget`, `budget_alert`.
- **Auditoría:** `audit_log` (append-only, hash encadenado).

Todas las tablas de negocio llevan `tenant_id` con RLS.

### 19.5 API (esbozo)

- REST versionada: `/api/v1/...` con recursos anidados por tenant y proyecto
  (p. ej. `/api/v1/projects/{id}/runs`, `/api/v1/projects/{id}/spec/rules`).
- El tenant se deriva de la sesión (no se confía en un parámetro del cliente).
- Eventos en tiempo real: `GET /api/v1/runs/{id}/events` (SSE).
- OpenAPI generado por FastAPI; cliente TypeScript generado desde él para el frontend.
- Paginación, filtros y errores con formato uniforme (RFC 9457 Problem Details).

---

## 20. Roadmap por hitos

Cada hito termina con: código en la rama, tests pasando en CI, documentación actualizada y una demo.

### M0 — Fundaciones

- Monorepo (uv workspace + pnpm), CI (lint, tipos, tests, SAST, SCA, secret scanning).
- Docker Compose local: PostgreSQL, Neo4j, Redis, MinIO, Keycloak, OpenFGA, Langfuse.
- FastAPI con OIDC (patrón BFF, cookies), sesión, CSRF.
- Tenants, usuarios, membresías, RLS, OpenFGA con roles base.
- Audit log append-only.
- Web: layout, login, menú por permisos, i18n, tema.

**Aceptación:** un usuario de un tenant no puede ver datos de otro (test automatizado a nivel API y SQL);
login con MFA en Keycloak local; toda acción sensible queda en la auditoría.

### M1 — Configuración IA y consumo

- Conexiones (Foundry, Bedrock, OpenAI) con "probar conexión" y secretos en Vault (dev: equivalente local).
- Catálogo familia → versión → oferta con sincronización; capacidades.
- Perfiles con esfuerzo normalizado y tabla de equivalencias; fallback.
- Cascada de configuración y matriz fase × rol.
- Gateway de modelos único; libro de consumo; precios versionados; presupuestos y alertas.
- Pantallas de Configuración IA y Consumo y costos.

**Aceptación:** una llamada de prueba por cada proveedor queda registrada con tokens y costo correctos;
superar un presupuesto pausa la ejecución; un agente no puede llamar a un proveedor sin pasar por el gateway.

### M2 — Proyectos e insumos

- CRUD de proyectos, asistente de creación (sin ejecutar agentes aún).
- Subida de insumos a object storage (validación, malware, hash, versión); conexión Git.
- Catálogo de agentes y skills (fichas, cards), recomendación determinista, validación de composición.
- Matriz de compatibilidad y plantillas de pipeline.

**Aceptación:** crear un proyecto CICS+BMS → Spring Boot + Angular + PostgreSQL + AWS propone el equipo y
las skills esperados; no se puede quitar un agente de Control; subir un zip con path traversal es rechazado.

### M3 — Motor de orquestación

- Composición dinámica de grafos LangGraph desde el proyecto; checkpointer PostgreSQL.
- Workers y cola; interrupts para compuertas; reanudación tras fallo.
- Patrón hacer → verificar → corregir con límites y escalamiento.
- Sandbox (Docker en dev) sin red.
- SSE de progreso; pestaña Ejecuciones en vivo; bandeja Mis tareas.

**Aceptación:** matar un worker a mitad de una fase y reanudar sin perder trabajo; una compuerta detiene el
flujo hasta la aprobación de un usuario con el permiso; la autocorrección respeta el máximo de iteraciones.

### M4 — Primer vertical completo: Sybase SP → destino + PostgreSQL

- Adaptador Sybase (inventario, tipos neutrales, extracción de reglas).
- Spec y revisión (C1), diseño (C3), generación por capas en el pack elegido (Java Spring Boot o .NET 10,
  ver decisión D-06).
- Golden master con Sybase ASE en contenedor y PostgreSQL; `verification` (compare, trace, proof pack, canario).
- Pestañas Especificación, Validación y Trazabilidad (versión inicial).

**Aceptación:** con la aplicación de referencia Sybase se obtiene un veredicto calculado por código; se miden
omisiones, alucinaciones y errores de precisión contra la spec de referencia.

### M5 — BMS → pantallas y prototipos

- Parser BMS determinista → spec de pantalla.
- Design system base NexTI y propuesta de prototipos navegables; comentarios e iteración (C2).
- Vista legacy ↔ prototipo.

**Aceptación:** todos los campos de los mapas de la aplicación de referencia aparecen en la spec de pantalla
con posición, longitud y atributos correctos.

### M6 — COBOL CICS

- Adaptador COBOL/CICS (inventario, clasificación, slicing, extracción).
- Transacción → Programa → Mapa en el grafo; importación de trazas para golden master.
- Visor de trazabilidad Legacy | Regla | Destino completo.

**Aceptación:** medición contra la spec de referencia CICS; veredicto máximo PARTLY PROVEN si no hay ejecución.

### M7 — Flujo 2 completo

- Ingesta de documentos, HU, Figma (API) y capturas (visión).
- Normalización, consolidación, detección de contradicciones y huecos, preguntas.
- Generación con contratos primero; validación de aceptación, contract tests y fidelidad visual.

**Aceptación:** con un set de HU + Figma de ejemplo se genera y valida una funcionalidad de punta a punta,
con cada elemento trazado a su insumo.

### M8 — ASPX / .NET Framework

- Adaptador ASPX (markup → pantallas, code-behind → reglas y contratos).
- Opción *uplift* a .NET 10 vs reescritura.
- Runner Windows en el sandbox.

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

### 22.2 Pendientes

| Id | Pregunta |
|---|---|
| D-06 | Destino del primer vertical Sybase: ¿Java Spring Boot o .NET 10? |
| D-11 | ¿NexTI solo informa el consumo de IA o también lo factura (con margen) cuando la cuenta es de NexTI? |
| D-12 | Neo4j Community (particionado por etiqueta) vs Enterprise (base por tenant) |
| D-13 | Cola de trabajos: Celery vs alternativa (Arq, Dramatiq, Temporal) |
| D-14 | Librería de componentes UI (shadcn/ui u otra) |
| D-15 | OpenFGA vs Casbin |
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
- **Internacionalización:** español e inglés.
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
  security-auditor, test-engineer, scaffolder, …), adaptados a español y a COBOL/Sybase/.NET bancario.
- **Scripts de verificación** como referencia de diseño para `packages/verification`:
  `compare.py` (comparación byte a byte con máscaras y tolerancias), `trace_rules.py` (regla → test),
  `proof_pack.py` (veredicto por reglas fijas).
- **Formatos de artefactos:** rule cards Given/When/Then, `topology.json`, `EQUIVALENCE.json`,
  `VERIFICATION.md/json`.

### 25.2 Qué aporta la plataforma y el plugin no tiene

Grafo persistente, multiusuario y multi-cliente, parsers deterministas, semántica de datos bancaria,
migración de datos, orquestación con presupuesto y reanudación gestionada, visor de trazabilidad,
completitud estructural, validación de reglas más allá de P0, y todo en español.

### 25.3 Lecciones de diseño adoptadas

- El estado vive en archivos/datos, no en la conversación.
- El validador es independiente y rehace el trabajo.
- Los conteos se leen de archivos del runner, nunca se tipean.
- El código analizado es input no confiable.
- El veredicto dice explícitamente lo que no prueba.
