# ADR-0038 — Preferencias del proyecto: arquitectura, estrategia de migración, artefacto y prácticas

- **Estado:** Aceptada · 2026-10-05
- **Secciones:** 8.4 (pack de destino), 7.7 (plan de migración), 6.1 (fases 6 y 8)
- **Relacionadas:** ADR-0033 (extracción guiada), ADR-0037 (versiones por eje)

## Contexto

Otra versión del producto dejaba elegir, al crear el proyecto, una preferencia de arquitectura libre ("preserve
topology"), patrones de diseño (Repository, CQRS, Strangler Fig...), prácticas de código (Clean Code, SOLID, DI, TDD),
plataforma y artefacto de despliegue. El aprobador pidió valorar cuáles aplican aquí.

El criterio de esta plataforma: una opción solo promete lo que el código puede verificar; lo demás se declara
orientativo. Además, la arquitectura elegida en el asistente **no llegaba al arquitecto**: el pedido de diseño no la
mencionaba.

## Decisión

- **Arquitectura `preserve-topology`** como opción del eje: un servicio por programa del legado, entidades espejo de
  las tablas. Una regla de compatibilidad lo recuerda al planificar.
- **Preferencias del proyecto** en el catálogo (`preferences` en `targets.yaml`), guardadas en `target.preferences` y
  validadas por el motor de composición (solo claves del catálogo):
  - `strategy`: reemplazo de una vez, strangler fig, capa anticorrupción;
  - `artifact`: imagen de contenedor, función serverless, paquete de servicio;
  - `practices`: Clean Code, SOLID, inyección de dependencias, TDD (varias a la vez).
- **La corrida las recibe planas** y, con la extracción guiada, se convierten en **orientación en palabras** para el
  arquitecto (pila y arquitectura, estrategia, artefacto, prácticas), el planificador de historias (estrategia: con
  strangler, cada ola deja un sistema que funciona y nombra la fachada) y el desarrollador (prácticas).
- **Qué no se promete:** los patrones de código (Factory, Mediator, Facade) no entran como opciones; nadie puede
  verificarlos. Repository, Adapter y CQRS ya están en la arquitectura hexagonal y en las opciones de arquitectura.
  Las prácticas se declaran orientativas en la propia pantalla; la verificación por herramientas (linters en el
  sandbox) queda para cuando las imágenes las traigan.

## Consecuencias

- Sin la opción guiada, ningún pedido cambia: las grabaciones valen.
- El arquitecto deja de diseñar a ciegas: sabe la pila, la arquitectura y la estrategia del proyecto.
- Las preferencias son datos del proyecto, visibles y auditables, no texto libre.
