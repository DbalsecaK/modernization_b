# ADR-0050 — PROVEN exige el legado cubierto o cada hueco con una decisión firmada

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 11.2 (veredicto), 10.4 (tarjetas de decisión), 11.4 (paquete de prueba)
- **Relacionadas:** ADR-0047 (cobertura del legado), ADR-0048 (quirks del motor), ADR-0049 (cobertura del destino),
  plan aprobado (paso 8)

## Contexto

Con ADR-0047 y ADR-0048 la plataforma sabe qué ramas del legado no entró ningún caso y qué quirks del motor no
alcanzó ninguno. Hasta ahora eran notas: el veredicto podía decir PROVEN con ramas sin probar. Exigir el 100 % sin
salida bloquearía programas con ramas que ninguna entrada alcanza (código muerto, defensas imposibles).

## Decisión

1. **Huecos del legado**: las ramas medibles que ningún caso confiable entró y los quirks que ningún caso alcanza
   (`legacy_gaps`), después de la única ronda de M27b con el test engineer.
2. **Decisión firmada antes de la verificación.** Si hay huecos, la fase de verificación pregunta primero, antes de
   cualquier trabajo, con una tarjeta de decisión (10.4) que los lista:
   - "Mantenerlos como no probados" (recomendada): nadie mostró que sean inalcanzables.
   - "Firmarlos como inalcanzables": quien responde afirma que ninguna entrada los alcanza y lo explica en el
     comentario. La respuesta queda auditada con su autor, como toda respuesta.
3. **Nuevo chequeo `legacy_covered`**, solo cuando el golden master midió la cobertura:
   - sin huecos, o con los huecos firmados como inalcanzables: pasa (con el firmante en el detalle y la evidencia);
   - con los huecos aceptados como no probados: `not_checked`, y el veredicto queda en PARTLY PROVEN.
4. **PROVEN** exige entonces: 100 % de equivalencia en los casos (`same_behaviour`), los seis chequeos de siempre y,
   si hubo medición, `legacy_covered` en verde, es decir, cero huecos o todos firmados, incluidos los quirks sin
   resolver.
5. **La cobertura del destino (ADR-0049) se lista y no bloquea**: es un hallazgo para el revisor, no una prueba de
   que el comportamiento difiera.
6. Un golden master sin cobertura medida (trazas, motores sin instrumentación) no tiene el chequeo y se rige por
   las reglas anteriores (las trazas ya limitan a PARTLY PROVEN).

## Consecuencias

- Las corridas con huecos esperan una respuesta en la verificación; con aprobación delegada se responde como
  cualquier otra tarjeta.
- Las grabaciones de aceptación no miden cobertura: sus veredictos no cambian.

## Cómo se valida

Pruebas del chequeo (sin huecos, firmados, aceptados; PROVEN frente a PARTLY PROVEN), de la lista de huecos y de la
fase: con una rama sin caso la verificación pregunta antes de cargar el diseño.
