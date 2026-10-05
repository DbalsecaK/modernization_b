# Plan del hito M19 — La suite de caracterización en piezas

- **Estado:** cerrado (2026-10-05).
- **Fuente:** secciones 6.1 (fase 9) y 11.1; ADR-0036 y D-55.
- **Rama:** `m19-suite-por-piezas`.

## 1. Motivo

La suite de caracterización era la única respuesta de modelo cuyo tamaño crecía con el programa entero. En un
procedimiento real superó tres veces el tope de salida. La orden del aprobador: resolverlo de raíz antes de meter
aplicaciones grandes.

## 2. Pasos

| # | Paso |
|---|---|
| 1 | `parse_schema`, `parse_cases`, `groups_of`, `affected_groups`, `unique_names` en la fase de caracterización; `work_guided` con el esquema primero y los casos por grupos de seis reglas; reintento por pieza señalada |
| 2 | Prueba: suite en piezas con un diagnóstico que repite solo su grupo; la suite unida cubre todas las reglas |
| 3 | ADR-0036 y D-55 |

## 3. Cierre

Sin la opción guiada el pedido es el de siempre: M4 y las demás grabaciones reproducen igual. Con la opción, el
procedimiento ficticio (9 reglas) hace un pedido de esquema y dos de casos.
