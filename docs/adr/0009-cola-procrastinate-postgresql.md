# ADR-0009 — Cola de trabajos con Procrastinate sobre PostgreSQL (D-13)

- **Estado:** Aceptada · 2026-09-29 (decisión del aprobador)
- **Secciones:** 10.2, 10.3, 19.1, 19.2, 20 (M3), 22 (D-13 pasa de pendiente a registrada)
- **Relacionadas:** ADR-0006 (excepciones a `tenant_id`), regla 3 de `CLAUDE.md`

## Contexto

La API no ejecuta agentes (regla 3): encola trabajos que toman workers. El criterio de M3 exige matar un worker a mitad
de una fase y reanudar sin perder trabajo. La durabilidad del trabajo en sí la da el checkpointer de LangGraph en
PostgreSQL; la cola tiene que entregar el trabajo al menos una vez, detectar pronto un worker muerto y no crear
ejecuciones fantasma (una ejecución registrada sin trabajo, o un trabajo sin ejecución).

## Decisión

- **Procrastinate** (cola asíncrona sobre PostgreSQL, `SELECT … FOR UPDATE SKIP LOCKED`): la API inserta la ejecución
  y su trabajo **en la misma transacción**.
- El worker marca **latidos**; un trabajo de un worker sin latido se reintenta en segundos y el grafo continúa desde su
  último checkpoint.
- Las tablas de la cola (`procrastinate_*`) y del checkpointer de LangGraph (`checkpoint*`) son **infraestructura sin
  `tenant_id`**: guardan solo referencias (ids de ejecución, fase, pregunta y claves de objetos), nunca datos del
  cliente. El estado de negocio (ejecuciones, fases, preguntas, eventos) vive en tablas con RLS.
- El diagrama de la sección 19.1 cambia "Cola (Redis)" por "Cola (PostgreSQL, Procrastinate)"; Redis sigue para las
  sesiones.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Arq (Redis) | El trabajo de un worker muerto solo se reintenta al vencer su bloqueo (el timeout del trabajo, que puede ser largo) y el encolado no es transaccional con la ejecución |
| Celery (Redis) | Síncrono en su diseño: incómodo con LangGraph y el gateway asíncronos; más configuración |
| Dramatiq | Mismos problemas de transaccionalidad que las colas sobre Redis |
| Temporal | Duplica lo que ya dan el checkpointer de LangGraph y la cola; un sistema más que operar |

## Consecuencias

- Un servicio menos que operar para las colas; el throughput de PostgreSQL alcanza para cientos de trabajos por
  segundo, muy por encima de lo que exigen las ejecuciones de modernización (pocas y largas).
- Las migraciones de Procrastinate se aplican desde Alembic (versión fijada).

## Cómo se valida

Test de integración con procesos reales: se mata el worker con SIGKILL a mitad de una fase, otro worker toma el
trabajo por falta de latido y la ejecución termina sin repetir las fases ya completadas.
