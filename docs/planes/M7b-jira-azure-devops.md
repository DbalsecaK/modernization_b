# Plan del hito M7b — Integración con Jira y Azure DevOps

- **Estado:** cerrado (2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 7.6 (backlog y ciclo de bugs), 7.7 (historias y plan), 17
  (Administración), 18.3 (asistente) y 20 (M7b); ADR-0019.
- **Rama:** `m7b-jira-azure-devops`. Un commit por paso y PR al terminar.
- **Decisiones (opción recomendada, 2026-10-01; el aprobador pidió avanzar sin preguntas):**
  - **Sin proyectos reales de Jira ni de Azure DevOps.** La aceptación usa servidores simulados con estado que siguen
    las APIs REST públicas (Jira Cloud v3 y Azure DevOps Work Item Tracking 7.1). El cliente real es el mismo: solo
    cambia la URL base.
  - **Credenciales.** Jira usa correo y token de API (Basic) y Azure DevOps usa un token personal (PAT). Viven en
    OpenBao, en la misma tabla de integraciones del tenant de M7. OAuth queda para después.
  - **Contenido del bug.** Lo escribe el código desde la evidencia del veredicto: pasos, esperado contra obtenido,
    regla y traza. El agente developer propone la corrección en el sandbox.
  - **Presupuesto de grabación.** La corrección automática llama al developer. El tope es 1 USD, dentro de los 10 USD
    de M7 y M7b.
  - **Visión sobre capturas.** Pasa a M8. Necesita que el gateway mande imágenes, un cambio de contrato con su propio
    ADR.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Conexiones Jira y Azure DevOps por tenant (URL, credencial en OpenBao, prueba) | OAuth |
| Vínculo por proyecto (pestaña Backlog): conexión, proyecto externo, mapeo de tipos, reglas activables | Sincronizar comentarios en los dos sentidos |
| Crear desde la spec al aprobar C1: features, historias aprobadas con su Gherkin y tareas, por ola, sin duplicados al re-sincronizar | Visión sobre capturas (M8) |
| Marcar como terminado con la evidencia cuando la verificación de sus reglas pasa | |
| Bug ante fallo del veredicto, corrección propuesta por el developer en el sandbox, re-test y revisión humana | |
| Toda escritura externa auditada e idempotente (`work_item_link`) | |
| Pestaña Backlog conectada | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0019 y D-38 |
| 2 | Paquete `nexti_integrations`: clientes de Jira y Azure DevOps, planificador del backlog (idempotente), pruebas con servidores simulados |
| 3 | Migración: configuración de la integración, vínculo de proyecto y `work_item_link`; API de conexiones Jira y Azure DevOps, vínculo, ítems y sincronización, con OpenFGA y auditoría |
| 4 | Worker: sincronización al aprobar C1 y al guardar un veredicto (terminado o bug) |
| 5 | Ciclo del bug: el developer propone la corrección en el sandbox, re-test y espera revisión humana |
| 6 | Pantallas: pestaña Backlog conectada y formularios de Jira y Azure DevOps en Integraciones |
| 7 | Aceptación con Jira y Azure DevOps simulados (y el developer grabado) |
| 8 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Aprobar C1 crea la jerarquía esperada, sin duplicados al re-sincronizar (Jira y Azure DevOps) | `test_acceptance_m7b.py` |
| Un test fallido crea un bug y el ciclo termina en revisión humana | `test_acceptance_m7b.py` (developer grabado) |
| Un usuario de otro tenant no ve ni usa la conexión | Pruebas de API de aislamiento |
| Toda escritura externa queda auditada | `test_acceptance_m7b.py` y pruebas de API |

## 4. Cierre

**Aceptación.** `test_acceptance_m7b.py` corre contra un Jira y un Azure DevOps simulados con estado, que responden las
APIs REST públicas que usan los clientes reales.

- **C1 en los dos sistemas.** La aprobación de C1 por la API encola la sincronización. El trabajo del worker crea la
  jerarquía esperada:
  - la feature;
  - las 3 historias aprobadas, con su Gherkin y su etiqueta de ola;
  - una tarea por regla vinculada.

  Repetir la sincronización no escribe nada. Cada escritura externa queda en la auditoría (`backlog.create`).
- **Ciclo del bug:**
  1. El veredicto de un proyecto generado con una línea de su servicio rota tiene el chequeo de tests en rojo.
  2. La sincronización abre el bug, con pasos, esperado contra obtenido, regla y traza.
  3. El developer propone la corrección en el sandbox de Java en 1 iteración y los 7 tests pasan.
  4. El bug queda *en revisión*, con la corrección como borrador en `bug_fix`, a la espera de una persona.
- **Aislamiento.** Las pruebas de API confirman que otro tenant no ve ni usa la conexión, y que un proyecto no puede
  vincular la integración de otro tenant.

El developer hizo 1 llamada grabada por 0,04 USD. El gasto real de M7b fue de 0,04 USD. De los 10 USD de M7 y M7b se
usaron cerca de 0,85.

**Cambios respecto del plan**

- La aceptación se hizo antes que las pantallas (paso 7 antes del 6), como en M7.
- La configuración de la integración (sitio y correo de Jira, URL de la organización de Azure DevOps) se verifica
  como host https público, igual que los repositorios, para evitar SSRF.
- Un bug cuyo chequeo vuelve a pasar en un veredicto nuevo se marca terminado, con ese veredicto como evidencia.

**Limitaciones conocidas**

- No hay proyectos reales de Jira ni de Azure DevOps. El comportamiento contra las APIs reales queda por probar con
  una cuenta de prueba del cliente; el cliente y la URL base son los de producción.
- El texto de los ítems está en inglés. Seguir el idioma de artefactos del proyecto (18.6) queda pendiente.
- No se sincronizan los comentarios en los dos sentidos. OAuth y la visión sobre capturas pasan a hitos siguientes.
- La corrección propuesta queda como borrador: aplicarla al código generado es una decisión de la persona que revisa.
  En esta versión se descarga desde el almacén de objetos; no hay todavía un botón para aplicarla.
