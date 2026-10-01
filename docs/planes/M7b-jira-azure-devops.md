# Plan del hito M7b — Integración con Jira y Azure DevOps

- **Estado:** en curso (desde 2026-10-01).
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
