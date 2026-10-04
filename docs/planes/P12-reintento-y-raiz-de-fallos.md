# Plan P12 — Reintento desde la fase fallida y causas de raíz de los fallos de corrida

- **Estado:** cerrado (2026-10-04).
- **Fuente:** secciones 10.4 y 11.1; ADR-0034 y D-53.
- **Rama:** `p12-reintento-y-raiz-de-fallos`.

## 1. Motivo

Tres corridas seguidas sobre un procedimiento real fallaron en Arquitectura o perdieron un slice de la extracción
por rechazos de la verificación por código que el modelo no supo corregir. Cada fallo obligaba a lanzar una corrida
nueva y a repetir todo, incluida la aprobación de C1 por otra persona.

## 2. Qué se hizo

| # | Cambio | Dónde |
|---|---|---|
| 1 | Reintento desde la fase fallida: nodo `retry` en el grafo, reanudación en el worker, `POST /runs/{id}:retry`, botón en la web, auditoría | orquestación, worker, API, web |
| 2 | Nombres del legado comparados sin marcadores ni caracteres invisibles; con extracción guiada, el error lista los nombres más parecidos | `generation.py` |
| 3 | Slices de más de doce trozos se tratan como fragmentados; en el último intento se conserva la regla que solo cita fuera del slice, para el verificador | `extraction.py` |
| 4 | ADR-0034, D-53, pruebas de motor, extracción, diseño y API | docs, pruebas |

## 3. Cierre

- Motor: una corrida fallida espera un reintento; al reintentar, la fase fallida corre de nuevo y las anteriores no
  se repiten (sin un segundo `runStarted`).
- Las grabaciones M4, M17 y M18 reproducen igual.
- Pendiente de observar en la práctica: si el arquitecto sigue inventando nombres con las pistas, el siguiente paso
  es pasarle la lista de parámetros y columnas reales en el pedido, lo que exige regrabar.
