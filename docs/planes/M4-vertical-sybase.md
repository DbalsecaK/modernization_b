# Plan del hito M4 — Primer vertical completo: Sybase SP → Java Spring Boot + PostgreSQL

- **Estado:** en ejecución (2026-09-29). Se avanza de corrido; solo se detiene ante una decisión importante.
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 4, 5, 6, 7.7, 8, 11, 20 (M4) y 21.
- **Rama:** `m4-vertical-sybase`, un commit por paso, PR a `main` al terminar.
- **Decisiones del aprobador (2026-09-29):**
  - **D-06:** el primer vertical Sybase migra a **Java Spring Boot**. La plataforma siempre pide el lenguaje
    destino en el asistente: Spring Boot es el primer pack que se construye, no un destino fijo (ADR-0010).
  - **Aplicación de referencia:** el SP real `sp_debcred_empresa` de Banco Bolivariano (2173 líneas), que tiene
    un proyecto de migración de Sybase a Java Spring Boot. Es código de cliente: **nunca entra al repositorio**;
    vive en un kit de referencia local fuera del repo (ADR-0011). El CI usa una aplicación ficticia propia.
  - **Golden master:** Sybase ASE 16 en contenedor local (imagen `datagrip/sybase`); las salidas legacy quedan
    grabadas como fixtures y el CI compara contra ellas sin levantar Sybase.
  - **Modelos:** respuestas grabadas en el CI de cada PR; evaluación con modelos reales a demanda, con tope de
    presupuesto por corrida (ADR-0012).

## 1. Alcance

| Incluye | No incluye (hito) |
|---|---|
| Adaptador Sybase ASE determinista: inventario (procedimientos, parámetros, tablas, temporales, cursores, llamadas, `@@error`/`@@rowcount`, transacciones), tipos neutrales, pistas de clasificación y slicing | BMS, CICS, ASPX (M5, M6, M8) |
| Grafo de conocimiento en Neo4j con una única capa de acceso que impone `tenant_id`/`project_id` (5.3, mínimo aceptable) | Visualización completa del grafo (M6) |
| Spec como dato estructurado (4.1): reglas con cita `archivo:línea`, tipos neutrales, escenarios con valores concretos, preguntas | Flujo 2 (M7) |
| Extracción de reglas por slice con agentes vía el gateway, cita verificada por código y revisor con otro modelo (11.2) | Jira / Azure DevOps (M7b) |
| Historias de usuario y plan por olas (7.7): editar, crear, dividir, fusionar, descartar, restaurar, versiones, auditoría, cobertura, validación Gherkin (en/es, web y servidor), plan sugerido y validado por código, C1 conjunto | Pack .NET 10 y otros destinos (mismo contrato, después) |
| Diseño (C3): modelo de dominio, contratos OpenAPI, ADR, fitness functions | |
| Pack Java Spring Boot + PostgreSQL: generación por capas (contratos → dominio → adaptadores → orquestación), cada capa compila y pasa sus tests en el sandbox | |
| Caracterización y golden master: ASE en contenedor local y PostgreSQL, fixtures grabadas | |
| Verificación independiente (11.3): tests, reglas trazadas, mismo comportamiento, inputs frescos, canario, fuente intacta → veredicto por código y proof pack | |
| Comparación origen ↔ destino por regla; pestañas Especificación, Validación y Trazabilidad (versión inicial) | |
| Evaluación contra la spec de referencia: omisiones, alucinaciones, errores de precisión (21.4) | |

## 2. Decisiones de diseño (sin detener el hito)

1. **Adaptador Sybase:** parser propio a nivel de sentencia (tokenizador T-SQL/Sybase con líneas exactas) y
   `sqlglot` (dialecto T-SQL) para las expresiones y referencias de tablas de cada sentencia. Nada del
   inventario usa IA (6.1, fase 2).
2. **Grafo:** Neo4j 5 Community (ya en Compose). Un módulo `packages/graph` es la única puerta: toda consulta
   lleva `tenant_id` y `project_id` como parámetros obligatorios y un test de arquitectura prohíbe Cypher fuera
   de él. La base por tenant (Enterprise, D-12) queda para el despliegue (M9).
3. **Spec relacional + grafo:** los elementos de la spec y las HU viven en PostgreSQL (RLS, versiones,
   auditoría); el grafo guarda nodos y aristas con referencias a ellos. El texto del código no entra al grafo.
4. **Agentes:** cada llamada a un modelo pasa por el gateway (regla de CLAUDE.md) con la conexión del tenant.
   El gateway gana un modo "grabar/reproducir" (cassettes) solo para tests: el CI reproduce; la evaluación
   graba con modelos reales (ADR-0012).
5. **Sandbox Java:** la generación compila y prueba en el sandbox sin red. Una imagen propia
   (`infra/sandbox/java`, Temurin 21 + Maven con las dependencias del pack ya descargadas) se construye local y
   en CI; el contenedor sigue sin red.
6. **Kit de referencia (ADR-0011):** carpeta local indicada por `NEXTI_REFERENCE_DIR` con el código legacy, la
   spec de referencia, casos de prueba y salidas legacy. Los tests que la necesitan se saltan sin ella; el CI
   usa `packages/adapters/sybase/tests/fixtures`, una aplicación bancaria ficticia escrita para el repo.
7. **Spec de referencia de Bolivariano:** las 39 reglas de `BUSINESS_RULES.md` revisadas por el aprobador
   (análisis previo con el plugin). Salió de una extracción revisada por una persona, no de una spec escrita a
   mano antes (21.2): las métricas lo declaran como sesgo conocido.
8. **Quién escribe las HU del Flujo 1:** el *Analista funcional* (7.7) cuando está en el equipo; el catálogo de M2 no
   lo recomienda para modernización, así que sin él las escribe el *Extractor de reglas* con el mismo prompt. Las
   dependencias entre HU no las decide el modelo: salen de los datos (una HU que lee una tabla que otra escribe).
9. **Permisos nuevos:** `story.edit` (dueño del proyecto, analista, revisor de negocio) y `plan.edit` (dueño
   del proyecto, arquitecto), registrados en 16.2 y en el catálogo.

## 3. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0010 (D-06), ADR-0011 (kit de referencia), ADR-0012 (respuestas grabadas y evaluación a demanda) |
| 2 | `nexti_core.spec` (19.3): modelo de la spec, tipos neutrales, validador Gherkin (en/es), plan por olas y cobertura |
| 3 | `packages/adapters/source/sybase`: tokenizador, inventario, tipos neutrales, clasificación, slicing; aplicación ficticia de referencia |
| 4 | `packages/graph`: capa de acceso a Neo4j con filtros obligatorios, carga del inventario y consultas (impacto, orden, huérfanos) |
| 5 | Migración 0008: spec, HU con versiones, plan y olas, artefactos generados, veredictos, evaluaciones; permisos `story.edit` y `plan.edit` |
| 6 | Gateway: grabar/reproducir para tests; agentes de extracción y revisión de reglas con cita verificada por código |
| 7 | Ejecutores reales: inventario, dominios, clasificación, extracción de reglas, HU y plan sugerido |
| 8 | API de spec, HU y plan: editar, crear, dividir, fusionar, descartar, restaurar, cobertura, validación, C1 conjunto |
| 9 | Diseño (C3) y pack Spring Boot: modelo de dominio, OpenAPI, generación por capas compilada en el sandbox Java |
| 10 | Caracterización y golden master: ASE en contenedor local, PostgreSQL, fixtures grabadas |
| 11 | Verificación independiente, veredicto por código y proof pack; comparación origen ↔ destino por regla |
| 12 | Evaluación contra la spec de referencia (omisiones, alucinaciones, precisión) |
| 13 | Web: Especificación (reglas, HU con Gherkin en vivo, plan por olas, preguntas) |
| 14 | Web: Validación (veredicto, proof pack) y Trazabilidad (origen ↔ destino por regla) |
| 15 | Aceptación de M4 con la aplicación ficticia; corrida con la referencia real a demanda |
| 16 | CI, cierre y PR |

## 4. Criterios de aceptación de M4 → tests

| Criterio | Test |
|---|---|
| Con la aplicación de referencia se obtiene un veredicto calculado por código | Aceptación con la aplicación ficticia (CI) y corrida a demanda con el kit de Bolivariano |
| Se miden omisiones, alucinaciones y errores de precisión contra la spec de referencia | Evaluación (paso 12) sobre ambas referencias |
| Mover una HU antes de una dependencia dura se rechaza (también por API); una blanda se permite con aviso | Validador del plan + API |
| Descartar una HU que deja reglas sin cubrir lo muestra en la cobertura | API de cobertura |
| C1 no se aprueba con HU con preguntas abiertas, sin criterios, con Gherkin inválido o con dependencias duras rotas | API de compuertas |
| Un escenario sin `When`, con pasos fuera de orden o con un `<placeholder>` fuera de `Examples` se rechaza (en/es, web y API) | Validador Gherkin + API + e2e |
| Todo cambio de HU o del plan queda versionado y auditado; sin permiso no se editan (permitido y denegado) | Matriz de autorización y tests de versiones |
