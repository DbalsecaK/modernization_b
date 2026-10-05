# Plan P15 — Reintento desde una fase elegida y máscaras del diseño

- **Estado:** cerrado (2026-10-05).
- **Fuente:** secciones 10.4, 6.1 y 11.3; ADR-0035 y D-54.
- **Rama:** `p15-reintento-por-fase-y-mascaras`.

## 1. Motivo

Veredicto NOT PROVEN en la primera corrida completa sobre un procedimiento real, por un diseño que enmascaró las
tablas de negocio y declaró infraestructura a los procedimientos de comisión. El reintento existente solo volvía a
la fase fallida (Verificación).

## 2. Qué se hizo

| # | Cambio | Dónde |
|---|---|---|
| 1 | `retry_from` en la corrida (migración 0021), `POST /runs/{id}:retry` con `phase` validada, nodo `retry` del grafo que salta a la fase elegida, reinicia las fases desde ella y vuelve a pedir sus compuertas | core, API, orquestación, worker |
| 2 | Selector de fase junto al botón de reintento | web |
| 3 | Con extracción guiada: restricciones de diseño en el pedido y verificación por código de máscaras, infraestructura y tablas escritas | `generation.py` |
| 4 | ADR-0035, D-54, pruebas de motor, diseño y API | docs, pruebas |

## 3. Cierre

- Motor: un reintento desde `ruleExtraction` tras fallar en diseño repite la extracción, vuelve a pedir C1 y conserva
  el preflight.
- Diseño: un diseño que enmascara una tabla citada por una regla, declara infraestructura un programa citado o deja
  sin entidad una tabla escrita recibe los tres problemas concretos; sin la opción, ninguno.
- Las grabaciones no cambian.
