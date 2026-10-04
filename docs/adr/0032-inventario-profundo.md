# ADR-0032 — Inventario profundo: bloques, descripciones, flujos por escenario y observaciones

- **Estado:** Aceptada · 2026-10-03
- **Secciones:** 4.1 (flujo de negocio), 5.2.1 (grafo interactivo), 6.1 (fases 2 a 6)
- **Relacionadas:** ADR-0011 (código del cliente), ADR-0012 (grabaciones)

## Contexto

Al probar la plataforma con un procedimiento grande, el grafo mostró un solo nodo para todo el SP y un solo flujo por
punto de entrada. La especificación (4.1) pide flujos de negocio con persona, resumen, reglas y pasos ordenados sobre
nodos del grafo, validados por negocio. Otra herramienta del equipo descompone el mismo SP en bloques lógicos, describe
cada bloque y propone flujos por escenario.

El aprobador pidió **sumar** esas capacidades al grafo actual, sin quitar ni reemplazar lo que ya tiene (impacto,
orden de migración, estado, huérfanos, foco por regla).

## Decisión

- **Bloques dentro de cada unidad, por código.** El adaptador de Sybase parte cada procedimiento en bloques lógicos:
  - los cortes son banners de comentario, `BEGIN TRAN`/`SAVE TRAN`, etiquetas destino de `GOTO` y ramas grandes;
  - cada bloque tiene sus líneas, su fase transaccional (antes, dentro, después, salida por error), las tablas que
    lee y escribe y los procedimientos que llama;
  - las relaciones entre bloques son *sigue a*, *salta a* y *sale por error*.

  Los párrafos de COBOL ya son bloques. El grafo guarda los bloques como nodos hijos de su unidad; la unidad sigue
  igual.
- **Lo que gasta modelos se suma con la opción de corrida `deep_inventory`.** Las corridas que lanza la web la llevan
  activada; las grabaciones existentes no, y siguen reproduciéndose igual:
  - **descripción de cada bloque y unidad** (3 a 5 líneas, a partir del extracto y sus conexiones), marcada como
    escrita por un modelo;
  - **observaciones del arquitecto** sobre el inventario;
  - **flujos por escenario:** después de consolidar las reglas, el analista propone escenarios con persona, resumen y
    pasos sobre bloques y reglas. El código valida que cada paso exista en el grafo; negocio los revisa en C1.
- **El grafo los muestra como agregado:** entrar a una unidad para ver sus bloques, agrupar por fase transaccional,
  descripción en el panel, flujos por escenario junto a los de punto de entrada, observaciones plegables, encabezado
  de resumen, barra de ayuda y marca de tablas sin DDL.
- **La extracción de reglas no cambia de slices.** Cambiar los slices cambiaría los pedidos al modelo y las
  grabaciones; los bloques mejoran la lectura del grafo, y la división automática de slices cortados ya cubre los
  procedimientos grandes.

## Consecuencias

- Una corrida nueva con `deep_inventory` hace algunas llamadas más (una corta por bloque y una por escenario).
- Las descripciones y observaciones son ayuda de lectura, no evidencia: el veredicto sigue calculándose por código.
