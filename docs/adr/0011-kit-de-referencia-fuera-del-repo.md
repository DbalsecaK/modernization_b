# ADR-0011 — Aplicaciones de referencia de clientes en un kit local, fuera del repositorio

- **Estado:** Aceptada · 2026-09-29
- **Secciones:** 15.3, 15.4, 20 (M4), 21
- **Relacionadas:** ADR-0010, regla de `CLAUDE.md` "nunca subir código ni secretos de clientes"

## Contexto

La evaluación de un adaptador (21) necesita una aplicación de referencia con su spec escrita por un experto, datos y
salidas esperadas. La primera referencia de M4 es un stored procedure real de Banco Bolivariano. Es código de
cliente: no puede entrar al repositorio ni a sus artefactos de CI, pero la plataforma tiene que poder evaluarse
contra él.

## Decisión

- Un **kit de referencia** es una carpeta local indicada por la variable `NEXTI_REFERENCE_DIR`, con una estructura
  fija por aplicación: código legacy, spec de referencia (reglas con prioridad, valores y ubicación aproximada),
  casos de prueba con entrada y salida esperada, y salidas legacy grabadas del golden master.
- Los tests y la evaluación que usan un kit **se saltan** si la variable no está. Nada del kit se copia al repo, a
  fixtures, a logs de CI ni a capturas.
- El CI usa una **aplicación de referencia ficticia** escrita para el repo (un SP bancario inventado, con reglas,
  tipos de precisión y rarezas), con su propia spec, casos y salidas: ejercita el vertical completo sin datos de
  clientes.
- Las métricas de cada corrida guardan el nombre y la versión (hash) del kit, no su contenido.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Subir el SP anonimizado al repo | Incluso anonimizado sigue siendo lógica del banco; el permiso es para I+D, no para publicarlo |
| Repositorio privado aparte con los kits | Posible más adelante; por ahora el kit lo tiene quien tiene el permiso del cliente |

## Consecuencias

- La corrida contra la referencia real se hace a demanda, en la máquina de quien tiene el kit (o en un runner
  privado en el futuro).
- La spec de referencia de Bolivariano salió de un análisis previo revisado por una persona, no de una spec escrita
  a mano antes de cualquier extracción (21.2); las métricas lo declaran como sesgo conocido.

## Cómo se valida

- Un test de arquitectura busca en el repo los identificadores del kit de Bolivariano y falla si aparecen.
- gitleaks y la revisión del diff antes de cada commit.
