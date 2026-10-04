# Plan del hito M18 — Extracción guiada de reglas

- **Estado:** cerrado (2026-10-04).
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

Aceptación M18 grabada con anthropic/claude-sonnet-5.5: 20 llamadas, 0,21 USD reales (0,17 USD en la extracción).
Mismo procedimiento ficticio y misma especificación de referencia (9 reglas, 5 de ellas P0):

| | Sin opción (M4) | Con `guided_extraction` (M18) |
|---|---|---|
| Reglas encontradas | 11 | 9 |
| Omisiones | 1 (RULE-009) | 1 (RULE-009) |
| Reglas inventadas | 3 | 1 |
| Errores de valor | 3 | 1 |
| Recall | 0,889 | 0,889 |
| Precisión | 0,727 | 0,889 |
| Llamadas de extracción | una por slice (12) | una por el programa entero |

Mejor precisión con el mismo recall. Queda pendiente la prioridad: salieron 8 reglas P0 contra 5 en la referencia. El
lente de criticidad no bajó ninguna; el aviso por código de C1 (más del 25 % de reglas P0) sí lo marca para la persona
que revisa.
