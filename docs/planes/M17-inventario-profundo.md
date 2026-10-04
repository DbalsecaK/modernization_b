# Plan del hito M17 — Inventario profundo

- **Estado:** cerrado (2026-10-04).
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

## 3. Cierre

**Lo que se entrega** (todo como agregado: nada del grafo anterior se quitó)

- **Bloques por código** (Sybase, `nexti_adapter_sybase.blocks`): cortes duros en etiquetas, `BEGIN/SAVE TRAN`,
  `COMMIT`/`ROLLBACK`; cortes por banners de comentario e `IF`/`WHILE` de más de 40 líneas; bloques chicos unidos al
  anterior. Cada bloque tiene nombre (banner, etiqueta o rango de líneas), fase (`pre`, `transaction`, `post`, `error`),
  tablas, llamadas y relaciones `NEXT`, `GOTO` y `ON_ERROR` (un salto tras chequear `@@error` o una variable de error).
  El procedimiento y sus relaciones quedan igual y el digest para los modelos no cambia.
- **API del grafo:** `parent`, `phase`, `schemaKnown` (tabla con `CREATE TABLE` en los insumos), relaciones nuevas y
  `summary`.
- **Insights con la opción `deep_inventory`** (las corridas de la web la llevan; las grabaciones existentes no):
  descripción de cada unidad y bloque, 3 a 8 observaciones y 2 a 6 flujos por escenario con persona, resumen, reglas y
  pasos validados contra el grafo, antes de C1. `GET /projects/{id}/graph/insights`.
- **Web:** entrar a una unidad y ver sus bloques, relaciones nuevas, agrupar por fase, descripción en el panel,
  escenarios en el selector de flujos, observaciones, resumen, ayuda y marca de tablas sin DDL (en/es).

**Evidencia**

- El SP ficticio da 10 bloques con sus fases y relaciones (pruebas del adaptador y de la API).
- `test_acceptance_m17.py` (grabada con modelos reales): 11 descripciones, 8 observaciones y 6 escenarios con todos sus
  pasos sobre nodos existentes; 3 llamadas nuevas por **0,068 USD reales**.
- Las aceptaciones grabadas de M4 y M10 se siguen reproduciendo igual: los pedidos a los modelos no cambiaron.

**Queda para después**

- Bloques para COBOL (los párrafos ya existen en el grafo, pero la API no los muestra como bloques) y para ASPX.
- Mostrar y editar los escenarios en la pestaña Especificación para la revisión de C1.
