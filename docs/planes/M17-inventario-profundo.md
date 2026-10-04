# Plan del hito M17 — Inventario profundo

- **Estado:** en curso (desde 2026-10-03).
- **Fuente:** secciones 4.1, 5.2.1 y 6.1; ADR-0032 y D-51.
- **Rama:** `m17-inventario-profundo`. Un commit por paso y PR al terminar.
- **Gasto:** aprobado por el aprobador sin consulta previa; tope de 2 USD por grabación.

## 1. Contrato de la API (para trabajar en paralelo)

`GET /api/v1/projects/{id}/graph` suma, sin quitar nada:

- nodos de tipo real `Block`, con `parent` (id de su unidad), `phase` (`pre`, `transaction`, `post`, `error`) y las
  líneas; `type` de dibujo `program`;
- en las tablas, `schemaKnown` (falso si solo se conocen porque el código las usa);
- relaciones nuevas `CONTAINS` (unidad → bloque, no se dibuja como línea), `NEXT`, `GOTO` y `ON_ERROR`;
- `summary`: `{modules, stores, relations, entryPoints}`.

`GET /api/v1/projects/{id}/graph/insights` (nuevo, `project.view`):

- `descriptions`: `{nodeId: texto}`;
- `observations`: `[texto]`;
- `scenarios`: `[{id, name, persona, summary, rules: [id], steps: [{title, nodes: [id], rule}]}]`;
- todo vacío si la corrida no tuvo `deep_inventory`.

## 2. Pasos

| # | Paso |
|---|---|
| 1 | Plan, ADR-0032 y D-51 |
| 2 | Bloques por código (Sybase), relaciones entre bloques, `summary`, `schemaKnown` |
| 3 | Descripciones, observaciones y flujos por escenario (opción `deep_inventory`), API de insights |
| 4 | Web: entrar a la unidad, agrupar por fase, descripción, escenarios, observaciones, resumen, ayuda, tablas sin DDL |
| 5 | Aceptación grabada con el SP ficticio, cierre y PR |
