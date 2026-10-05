# Plan del hito M22 — Estudio de adaptadores

- **Estado:** cerrado (2026-10-05).
- **Fuente:** secciones 8.1, 8.2 y 8.6; ADR-0039 y D-58.
- **Rama:** `m22-estudio-de-adaptadores`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `nexti_core.declarative_adapter`: `AdapterSpec` validada y `DeclarativeAdapter` con el contrato de 8.2; resumen para el estudio |
| 2 | `tenant_adapter` (migración 0023, RLS) y modelo ORM |
| 3 | API `/api/v1/adapters`: listar, crear, actualizar, borrar, `:try`, `:draft` (modelo por el gateway, validado por código); el catálogo del cliente suma sus adaptadores y opciones |
| 4 | Worker: los adaptadores del cliente se registran al arrancar la corrida; `pick_adapter` los considera |
| 5 | Web: estudio en la pestaña de adaptadores del catálogo (borrador con IA, prueba sobre muestras, guardar, borrar) |
| 6 | Pruebas del adaptador declarado, de la API y de autorización; ADR-0039 y D-58 |

## 2. Cierre

Un adaptador declarado queda como experimental: inventaría, clasifica y extrae reglas; no tiene motor para el golden
master, así que el veredicto no pasa de PARTLY PROVEN. El camino a certificado queda escrito en el ADR.
