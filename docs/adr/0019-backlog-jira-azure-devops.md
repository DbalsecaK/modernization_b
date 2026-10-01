# ADR-0019 — Backlog en Jira y Azure DevOps: sincronización idempotente y ciclo del bug

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 7.6 (backlog y ciclo de bugs), 7.7 (historias), 11.1 (autocorrección), 17, 18.3, 20 (M7b)
- **Relacionadas:** ADR-0007 (OpenBao), ADR-0018 (integraciones del tenant), ADR-0012 (grabaciones)

## Contexto

Al aprobar C1, el cliente quiere ver en su Jira o Azure DevOps lo que se va a construir, en el orden del plan. Cuando
la verificación pasa, quiere ver los ítems terminados con su evidencia. Cuando falla, quiere un bug que el equipo de
agentes intente corregir.

Las escrituras externas pueden fallar a mitad de camino y repetirse: una re-sincronización nunca debe duplicar ítems.
El contenido que viene de Jira o Azure DevOps no es confiable.

## Decisión

- **Un contrato de rastreador** (`BacklogTracker`), con dos implementaciones sobre las APIs REST públicas:
  - **Jira Cloud v3:** crear issue, transicionar, comentar, buscar por etiqueta.
  - **Azure DevOps WIT 7.1:** crear y actualizar work items con JSON Patch, comentar, consultar con WIQL.

  La URL base viene de la conexión; las pruebas apuntan a servidores simulados que siguen esas APIs.
- **Idempotencia por `work_item_link`.** Cada elemento de la plataforma tiene a lo sumo un ítem externo por proyecto
  vinculado:
  - una feature, una historia, una tarea por regla o pantalla de la historia, o un bug por chequeo fallido;
  - la tabla guarda su id y su clave externos, su estado y su huella de contenido.

  El planificador es código puro: compara lo que la spec pide con lo vinculado y produce solo las acciones que faltan
  (crear, actualizar, transicionar).
  - Si una escritura se cae a mitad de camino, la siguiente sincronización busca el ítem por su etiqueta
    `nexti-<elemento>` antes de crearlo.
- **Qué se crea al aprobar C1:**
  - las features de las historias aprobadas;
  - las historias, con su narrativa, sus criterios Gherkin y sus vínculos a reglas y pantallas;
  - una tarea por elemento vinculado.

  El orden y la ola van como etiquetas (`ola-1`...). El mapeo de tipos es configurable por proyecto.
- **Terminado con evidencia.** Al guardar un veredicto, una historia cuyas reglas están todas verificadas pasa a *Done*
  con un comentario: el veredicto, sus chequeos y la clave del paquete de prueba.
- **Ciclo del bug:**
  1. Un chequeo fallido de un veredicto crea un bug con pasos, esperado contra obtenido, regla y traza. El contenido
     lo escribe el código desde la evidencia.
  2. El developer recibe el fallo y propone la corrección en el sandbox.
  3. El código vuelve a correr los tests.
  4. El ciclo termina siempre en revisión humana:
     - si pasa, el bug queda *en revisión* con la corrección como borrador;
     - si no, se reabre con el nuevo resultado y, al superar el máximo de iteraciones, escala a una persona.

  Cerrar un bug en Jira no cambia un veredicto.
- **Seguridad:**
  - Credencial del tenant con alcance mínimo, solo en OpenBao.
  - Toda escritura externa queda en la auditoría, con el tipo, el elemento y la clave externa, nunca el token.
  - El vínculo de proyecto lo gestiona quien tiene `project.configure`.

## Alternativas consideradas

- **Que el agente redacte el bug.** Cuesta una llamada por fallo y puede inventar detalles. La evidencia ya trae lo
  que el bug necesita.
- **Buscar siempre por etiqueta antes de escribir, sin tabla de vínculos.** Depende de la búsqueda del sistema externo,
  que en Jira tiene retardo de indexación. La tabla es la fuente; la etiqueta solo recupera un ítem tras una caída.
- **Aplicar la corrección del developer directamente.** Viola la revisión humana: queda como borrador.

## Consecuencias

- Las reglas *sincronizar comentarios* y *visión sobre capturas* quedan fuera de M7b.
- Los cambios de alcance después de C1 actualizan los ítems vinculados (título y descripción) en la siguiente
  sincronización. No se borran ítems externos: se marcan como descartados con un comentario.

## Cómo se valida

- Pruebas del planificador y de los clientes contra servidores simulados de Jira y Azure DevOps.
- Pruebas de API: OpenFGA por endpoint, aislamiento entre tenants y auditoría.
- `test_acceptance_m7b.py` cubre lo siguiente:
  - C1 crea la jerarquía en los dos sistemas, sin duplicados al repetir;
  - un fallo crea el bug y el ciclo termina en revisión humana;
  - otro tenant no ve la conexión.
