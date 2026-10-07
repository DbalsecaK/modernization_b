# Plan del hito M26 — Escalación explicable

- **Estado:** cerrado (2026-10-07).
- **Fuente:** secciones 10.4, 11.1 y 9.2; ADR-0045 y D-65; petición del usuario sobre la pantalla de "intentos
  agotados" (ver el código que no pasó, la versión anterior, y un análisis con respuestas propuestas y confianza).
- **Rama:** `m26-escalacion-explicable` (sobre P31).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `Option.confidence`/`instruction`, `Explanation`, `Answer.comment`; `do_verify_correct(explain=…)` con la pregunta construida desde la explicación y la instrucción hacia la siguiente ronda |
| 2 | `escalation.py`: evidencia (diagnóstico, último intento, versión anterior) y análisis con `code-reviewer` (prompt `escalation-analyst`) |
| 3 | Cableado en pruebas, servicio, adaptadores y convergencia; el worker entrega el comentario de la respuesta |
| 4 | Web: `EvidencePanels` (análisis, diagnóstico, código con líneas señaladas, diferencia) y confianza por opción; `model.ts` con diff por líneas |
| 5 | Pruebas: `test_escalation.py`, `model.test.ts`; ADR-0045, D-65 |

## 2. Cierre

Validado con las suites de orquestación, worker y web. La siguiente escalación real de la corrida 44027f4f muestra
la evidencia y el análisis en la aplicación.
