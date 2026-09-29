# Plan del hito M2 — Proyectos e insumos

- **Estado:** terminado (2026-09-28). Criterios y evidencia en la sección 7.
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 7.1, 8.3–8.7, 9, 15.3–15.4, 18.3, 19.4 y 20 (M2).
- **Rama:** `m2-proyectos-insumos`, un commit por paso, PR a `main` al terminar.

## 1. Alcance

| Incluye | No incluye (hito) |
|---|---|
| CRUD de proyectos y asistente de creación de 9 pasos conectado (sin ejecutar agentes) | Ejecución del pipeline, workers y agentes (M3) |
| Configuración del proyecto **versionada**: orígenes, destino, agentes y skills con versión fijada, plantilla, autonomía, iteraciones, muestreo | Cambios de configuración que afecten fases ya iniciadas (M3, cuando existan fases) |
| Catálogo global de agentes, skills, orígenes, packs de destino, reglas de compatibilidad y plantillas de pipeline, cargado desde archivos versionados en el repositorio | Agentes y skills propios del tenant con aprobación y evaluación (necesitan ejecuciones: M3+) |
| Recomendación **determinista** del equipo y de las skills (con motivo), validación de la composición (fases cubiertas, Control obligatorio, conflictos, faltantes) y avisos de compatibilidad | Lectura de la estructura de Figma por API (M7) |
| Subida de insumos a object storage (MinIO en desarrollo) con validación de tipo y tamaño, seguridad de zip, malware, secretos, hash y versión | Clonado o instantánea del repositorio Git (lo hace el preflight en M3) |
| Referencias de UI desde el paso 2: capturas (mismas validaciones), links de Figma validados y links de prototipos con notas | Vínculo con Jira / Azure DevOps (M7b): la sección del asistente queda visible como "más adelante" |
| Conexión Git del proyecto (URL, rama, token en OpenBao) con prueba segura (sin SSRF) | Cifrado con llave por tenant en el object storage (despliegues, M9) |
| Pantallas conectadas: Proyectos, asistente, pestañas Resumen, Insumos y Configuración del proyecto, y Catálogo | El resto de las pestañas del proyecto (se llenan desde M3; muestran un estado vacío honesto) |

## 2. Decisiones de diseño (sin detener el hito)

1. **Catálogo como datos versionados en el repositorio** (sección 19.3): las fichas de agentes en
   `packages/agents` (YAML; los prompts llegan en M3), las skills en `packages/skills` (`SKILL.md` con metadatos,
   formato de las skills de Claude) y los orígenes, packs, reglas de compatibilidad y plantillas junto al motor de
   composición en `packages/core` (`nexti_core.composition`). Un comando `catalog-sync` los carga en tablas
   globales (excepción de catálogo, ADR-0006) sin borrar versiones anteriores: el proyecto fija versiones.
2. **Motor de composición puro** (`nexti_core.composition`): recibe el catálogo y el pedido y devuelve equipo con
   motivos, skills, avisos, conflictos, faltantes y fases sin cubrir. Las reglas son datos (condiciones sobre flujo,
   orígenes y ejes del destino), no `if` en el código. El mismo motor valida en el servidor al crear o cambiar la
   configuración; la web ya no decide nada (`apps/web/src/lib/recommend.ts` desaparece).
3. **Validación de insumos síncrona en la API** con límites de tamaño configurables (no es un agente: regla 3). El
   archivo pasa por `packages/ingest` antes de guardarse; un insumo rechazado no llega al object storage pero queda
   registrado (motivo) y auditado. En M3 la misma función puede correr en un worker sin cambios.
4. **Malware con ClamAV** (`clamd`, protocolo INSTREAM) en Compose y CI; si el escáner no está disponible la subida
   falla cerrada (ADR-0008, D-31).
5. **Secretos:** el cliente KV de OpenBao pasa de `nexti_model_gateway.secrets` a `nexti_core.secrets` para
   guardar también el token Git del proyecto. Sigue siendo **un único módulo** que habla con OpenBao (ADR-0007);
   las credenciales de proveedores de modelos solo las usa el gateway (el test de arquitectura se ajusta).
6. **Git sin SSRF:** la prueba de conexión hace `info/refs` por HTTPS con `httpx` (sin binario `git`), rechaza hosts
   que resuelven a direcciones privadas, de loopback o reservadas, y no sigue redirecciones.
7. **Presupuesto, modelos y equipo del asistente** reutilizan lo existente: `budget` (M1, del proyecto, total),
   `model_assignment` (M1, nivel proyecto × rol; personalizar exige `models.configure`) y `role_assignment` (M0; el
   creador queda como dueño del proyecto).

## 3. Modelo de datos (migración 0006)

| Tabla | Alcance | Notas |
|---|---|---|
| `agent_definition`, `skill_definition` | global (catálogo) | clave + versión; fichas de 9.2 y 9.5 |
| `source_option`, `target_option`, `compatibility_rule`, `pipeline_template` | global (catálogo) | orígenes por flujo, opciones por eje con nivel y ola, reglas como condiciones, plantillas con fases y compuertas |
| `project` (+ columnas) | tenant (RLS) | flujo, idioma de artefactos, descripción, creador |
| `project_config` | tenant (RLS) | versionada, solo inserción: orígenes, destino, plantilla, autonomía, iteraciones, muestreo, avisos |
| `project_agent`, `project_skill` | tenant (RLS) | por versión de configuración, con la versión del catálogo fijada y el motivo de la recomendación |
| `input_artifact` | tenant (RLS) | tipo, nombre lógico, versión, estado, clave del objeto, tamaño, sha256, tipo MIME, URL (links), notas, hallazgos, motivo de rechazo |
| `project_repository` | tenant (RLS) | URL, rama, `vault_path` del token, estado y última prueba |

## 4. Endpoints

| Recurso | Operaciones | Permiso |
|---|---|---|
| `/catalog` y `/catalog/skills/{key}` | el catálogo completo (sin el contenido de las skills) y el `SKILL.md` de una skill | miembro del tenant |
| `/projects:compose` | recomendación y validación de una composición (sin guardar) | miembro del tenant |
| `/projects` | listar (ya existe, se amplía), crear con toda la configuración | ver: OpenFGA; crear: `project.create` |
| `/projects/{id}` | ver, editar nombre y descripción, archivar | `project.view` / `project.configure` |
| `/projects/{id}/config` | nueva versión; historial | `project.configure` (+ `agents.select` / `skills.select` si cambian) / `project.view` |
| `/projects/{id}/inputs` | listar, subir (multipart), `:link` (Figma o prototipo), contenido, eliminar | `project.view` / `input.upload` (contenido de código: `code.download`) |
| `/projects/{id}/repository` | ver, configurar, `:test`, quitar | `project.view` / `input.upload` |

## 5. Criterios de aceptación de M2 → tests

| Criterio | Test |
|---|---|
| Un proyecto CICS + BMS → Spring Boot + Angular + PostgreSQL + AWS propone el equipo y las skills esperados | Unitario del motor (equipo y skills exactos, con motivo) e integración de `POST /projects:compose` |
| No se puede quitar un agente de Control | Motor (bloqueo), API (`422 control_agent_required` al crear y al cambiar la configuración) y e2e (la card no se puede desmarcar) |
| Subir un zip con path traversal es rechazado | `packages/ingest` (`../`, rutas absolutas, unidades de Windows, barras invertidas, enlaces simbólicos, zip bomb) e integración de la subida (422, nada en MinIO, rechazo auditado) |
| Un link de Figma que no es `figma.com/file|design|proto` se rechaza y una captura pasa por las mismas validaciones | Validador de links (unitario) y API; captura con tipo falso, EICAR (construido en tiempo de ejecución) y sobredimensionada rechazadas por el mismo pipeline |
| Permitido y denegado por endpoint, aislamiento entre tenants, auditoría de toda mutación (reglas de CLAUDE.md) | Matriz de `test_endpoints_authz.py` y test de aislamiento de proyectos, insumos y repositorio |

## 6. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0008 (validación de insumos y ClamAV) y D-31 |
| 2 | Catálogo como datos (`packages/agents`, `packages/skills`, `nexti_core.composition`) y motor de composición con tests |
| 3 | Migración 0006, tablas de catálogo y de proyecto con RLS, `catalog-sync` y semilla |
| 4 | `packages/ingest`: validación de archivos y links, secretos, cliente de ClamAV; ClamAV en Compose y CI |
| 5 | Object storage y secretos en `nexti_core`; conexión Git segura |
| 6 | Endpoints de catálogo, composición y proyectos con matriz de autorización y aislamiento |
| 7 | Endpoints de insumos y repositorio con matriz de autorización y aislamiento |
| 8 | Web: Catálogo conectado |
| 9 | Web: Proyectos y asistente conectados |
| 10 | Web: pestañas Resumen, Insumos y Configuración del proyecto |
| 11 | Recorrido de aceptación, CI y cierre |

Los once pasos están hechos, un commit por paso en la rama `m2-proyectos-insumos`.

## 7. Cierre de M2 (2026-09-28)

Los criterios de aceptación de la sección 20 de la especificación se cumplen con tests automatizados que corren en CI
contra los servicios reales (PostgreSQL, OpenFGA, OpenBao, MinIO, ClamAV, Keycloak).

| Criterio | Evidencia (tests) | Estado |
|---|---|---|
| Un proyecto CICS + BMS → Spring Boot + Angular + PostgreSQL + AWS propone el equipo y las skills esperados | `packages/core/tests/test_composition.py` (17 agentes con su motivo y 13 skills exactos), `test_projects.py::test_compose_proposes_the_expected_team_and_skills` (API) y `e2e/projects.spec.ts` (asistente) | ✅ |
| No se puede quitar un agente de Control | Motor (`test_a_control_agent_cannot_be_removed`), API al crear y al cambiar la configuración (`422 control_agent_required`) y e2e (card bloqueada en el asistente y en Configuración) | ✅ |
| Subir un zip con path traversal es rechazado | `packages/ingest/tests/test_ingest.py` (`../`, rutas absolutas, unidades, barras invertidas; además enlaces simbólicos, cifrado y zip bombs), `test_inputs.py::test_a_zip_with_path_traversal_is_rejected_and_nothing_is_stored` (422, nada en MinIO, rechazo auditado) y e2e | ✅ |
| Un link de Figma que no es `figma.com/file\|design\|proto` se rechaza y una captura pasa por las mismas validaciones | `test_ingest.py` (links aceptados y rechazados; capturas con tipo falso, sobredimensionadas o truncadas; ClamAV sobre capturas) y `test_inputs.py::test_figma_and_prototype_links` / `test_screenshots_go_through_the_same_validation` | ✅ |
| Permitido y denegado por endpoint, aislamiento entre tenants y auditoría de toda mutación (reglas de CLAUDE.md) | `test_endpoints_authz.py` (matriz de las rutas nuevas con un usuario ajeno al tenant, subida multipart incluida), `test_projects.py` y `test_inputs.py` (aislamiento), `test_rls.py` (tablas nuevas) | ✅ |
| Nada del catálogo ni de una configuración se cambia en el lugar | `test_rls.py::test_the_agent_catalog_and_project_configurations_are_not_editable_in_place` y `test_catalog_store.py` (versión nueva obligatoria) | ✅ |

**Capturas** en `docs/m2/`: catálogo, equipo y skills propuestos por el asistente, resumen del proyecto, insumos con un zip
rechazado (y su motivo) y los aceptados versionados, y la configuración con su historial.

**Cambios respecto del plan**

- El catálogo se sirve en un solo `GET /catalog` (más `GET /catalog/skills/{key}` con el `SKILL.md`), porque el
  asistente y la pantalla de Catálogo lo necesitan completo.
- `POST /projects:compose` también verifica el perfil de modelo que usaría cada agente contra sus capacidades (9.4);
  es un aviso, porque los modelos pueden configurarse antes de ejecutar.
- Al crear un proyecto, la API publica las tuplas de OpenFGA antes de responder (espera acotada) para que el creador
  lo abra de inmediato.
- Contraste AA de la insignia "info" (token `info-ink`) y franja de fases accesible por teclado: los detectó axe.
- La guarda de la auditoría rechazó claves que parecían credenciales (`secrets`, `token_changed`): se renombraron.

**Limitaciones conocidas (pasan a hitos posteriores)**

- La validación es síncrona en la API (límites de 200 MB para zips, 25 MB para documentos y 10 MB para capturas): los
  insumos grandes pasan a los workers de M3 con la misma función.
- La prueba de Git resuelve el host antes de pedir `info/refs`; queda el riesgo residual de DNS rebinding, que el
  sandbox sin red interna de M3 cierra para el clonado.
- El object storage usa en desarrollo las credenciales raíz de MinIO; un despliegue da a la API un usuario limitado a
  su bucket y llaves por tenant (M9).
- Agentes y skills propios del cliente, lectura de Figma por API (M7) y vínculo con Jira / Azure DevOps (M7b).
- Las demás pestañas del proyecto muestran un estado vacío hasta que el pipeline produzca su contenido (M3+).
