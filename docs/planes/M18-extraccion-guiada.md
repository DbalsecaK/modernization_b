# Plan del hito M18 — Extracción guiada de reglas

- **Estado:** en curso (2026-10-04).
- **Fuente:** secciones 6.1 (fase 5), 11.1 y 11.2; ADR-0033 y D-52.
- **Rama:** `m18-extraccion-guiada`. Un commit por paso y PR al terminar.
- **Gasto:** el aprobador pidió aplicar los siete puntos sabiendo que requieren una grabación con modelos reales;
  tope de 2 USD.

## 1. Contrato

- `POST /api/v1/projects/{id}/runs` acepta `guidedExtraction` (booleano). En las corridas `pipeline` vale verdadero
  salvo que llegue `false`. La corrida guarda `options.guided_extraction`.
- `GET /api/v1/projects/{id}/c1-check` suma en `warnings` los avisos de la extracción guiada:
  - demasiadas reglas P0;
  - texto con forma de instrucción en el fuente.
- No cambian los esquemas de reglas, historias ni clasificación.

## 2. Pasos

| # | Paso |
|---|---|
| 1 | Módulo `guided`: mapa del programa, programas chicos completos, avisos por código, corrección de citas, lentes, consolidación por significado; prompts nuevos; opción de corrida; pruebas unitarias |
| 2 | Plan, ADR-0033 y D-52 |
| 3 | Aceptación M18 grabada (tope 2 USD) y comparación con M4 contra la especificación de referencia |
| 4 | CI, PR y cierre |

## 3. Cierre

Se completa al terminar el paso 4.
