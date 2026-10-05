# ADR-0035 — Reintento desde una fase elegida y máscaras del diseño verificadas contra las reglas

- **Estado:** Aceptada · 2026-10-05
- **Secciones:** 10.4 (ciclo de vida de una corrida), 6.1 (fase 8, diseño), 11.3 (equivalencia y máscaras)
- **Relacionadas:** ADR-0033 (extracción guiada), ADR-0034 (reintento desde la fase fallida)

## Contexto

La primera corrida completa sobre un procedimiento real terminó en **NOT PROVEN**: los 21 casos del golden master
difieren del código generado. La causa estaba en el diseño, aprobado sin revisión porque C3 no era obligatoria:

- el arquitecto dejó fuera, con máscaras `tables:`, las tablas de órdenes y detalle, por lo que el Java no puede
  responder "orden no encontrada";
- declaró infraestructura a los procedimientos de comisión y grabación de la transacción, que son el negocio.

Y una vez rechazada C4, el reintento (ADR-0034) solo volvía a Verificación, que no arregla un diseño malo: había que
lanzar una corrida nueva y repetir inventario, extracción, historias, C1 y el golden master.

## Decisión

### Reintento desde una fase elegida

- `POST /runs/{id}:retry` acepta `phase`: la fase fallida o una anterior. La API valida contra las fases registradas
  de la corrida y guarda la elección en `run.retry_from` (migración 0021).
- El grafo salta a esa fase. Las fases desde ella en adelante empiezan de cero (diario e identificadores nuevos),
  sus filas vuelven a *pendiente* y **sus compuertas se piden de nuevo**: un diseño nuevo exige una C3 nueva y una
  C4 nueva. Las decisiones anteriores quedan en la auditoría.
- Lo anterior a la fase elegida conserva sus resultados: reglas, historias, C1 y el golden master.
- La web ofrece la fase en un selector junto al botón de reintento, limitado a la fallida y las anteriores.

### Máscaras del diseño verificadas contra las reglas (extracción guiada)

Con la opción `guided_extraction`, el pedido al arquitecto lleva las restricciones y el código las verifica:

- una máscara `tables:` se rechaza cuando una regla aprobada cita líneas que leen o escriben esa tabla;
- un programa de `infrastructure` se rechaza cuando una regla cita líneas que lo llaman: es negocio y necesita un
  puerto con `legacy_program`;
- toda tabla que el programa escribe (según el inventario) necesita una entidad con `legacy_table` o una máscara
  con razón;
- (precisión del 2026-10-05) una máscara `tables:` se rechaza también cuando el programa **lee** esa tabla en las
  40 líneas anteriores a una línea que una regla cita: los valores que carga alimentan la regla (el `SELECT` de
  configuración que precede al `IF` que la regla cita). Una corrida real había enmascarado la tabla de
  configuración contable como infraestructura y el código generado nunca producía el error ni la comisión que el
  legado sí producía (59/59 casos distintos).

Las razones de infraestructura legítimas (registro de errores y eventos, auditoría) no citan reglas y siguen
permitidas. Sin la opción no cambia ningún pedido: las grabaciones (M4, M6, M6c, M8b, M10, M11) valen igual.

## Consecuencias

- Rechazar C4 por un mal diseño cuesta ahora solo diseño, generación y verificación, no toda la corrida.
- Un diseño que esconde negocio no llega a C3: el modelo recibe el problema concreto y lo corrige, o la fase falla
  con el motivo.
- Recomendación operativa: marcar C3 como compuerta obligatoria en los proyectos reales; la verificación por código
  reduce el riesgo, no sustituye la revisión del arquitecto humano.
