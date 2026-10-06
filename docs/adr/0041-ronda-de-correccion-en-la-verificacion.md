# ADR-0041 — Ronda de corrección en la verificación (extracción guiada)

- **Estado:** Aceptada · 2026-10-05
- **Secciones:** 10.3 (generación), 11.3 (verificación independiente), 11.4 (paquete de evidencia)
- **Relacionadas:** ADR-0033 (extracción guiada), ADR-0035 (reintento por fase y máscaras), ADR-0017 (packs)

## Contexto

La generación escribe el servicio y los adaptadores a partir del diseño, las reglas y sus pruebas unitarias; la
verificación compara después el destino con el golden master y dictamina. Nadie devolvía al desarrollador las
diferencias: tres corridas reales sobre el mismo procedimiento terminaron NOT PROVEN con 60/65 casos distintos por
una sola sentencia (un `UPDATE` cuyo `WHERE` el generador reescribió "a su manera"), sin que ningún agente la
viera jamás junto al resultado del legado.

## Decisión

Con la opción `guided_extraction`, cuando el golden master difiere y el arnés sí corrió:

1. La verificación agrupa las diferencias por ruta (`returns`, `outputs:@x`, `tables:t[0].col`, `calls`), con
   cuántos casos y qué casos las muestran y el primer valor del legado y del destino.
2. Extrae del legado, numeradas, las líneas que nombran las tablas y programas de las diferencias (±6 líneas) y las
   líneas que citan las reglas de los casos que fallan (a lo sumo 160 líneas).
3. Se las entrega al **desarrollador** (`backend-dev`, fase `verification`) con el servicio del caso de uso y los
   adaptadores que nombran esas tablas o programas (a lo sumo 4 archivos). Las instrucciones son concretas:
   mismos predicados del SQL del legado, mismo orden de llamadas, salidas NULL donde el legado las deja NULL,
   errores solo donde el legado los lanza. Responde con los archivos que cambia (`### ruta` + bloque de código).
4. El destino corregido se compila y pasa sus pruebas; si no, la ronda se descarta y el diagnóstico vuelve en la
   siguiente. Si compila, corre el golden master otra vez: la corrección se queda solo si **reduce** los casos que
   difieren; entonces se guarda como artefacto (misma ruta, misma trazabilidad de reglas).
5. A lo sumo **dos rondas**; después, el veredicto de siempre sobre el código final. Cada ronda queda en el
   paquete de evidencia ("Correction round n (archivos): antes -> después") y en los eventos de la corrida.

Sin la opción no cambia ninguna petición: las grabaciones (M4, M6, M6c, M8b, M10, M11) valen igual.

## Consecuencias

- El veredicto sigue siendo independiente: lo computa el código sobre el golden master, y las rondas se declaran
  en el paquete de evidencia. Lo que cambia es que el desarrollador deja de ir a ciegas.
- Costo acotado: dos llamadas del desarrollador y dos compilaciones más por verificación, en el peor caso.
- Límite honesto: corrige desviaciones localizadas (predicados, orden, salidas); no rehace el diseño. Si el
  diseño es la causa, el camino sigue siendo el reintento desde Architecture (ADR-0035).

- (2026-10-06) Con ADR-0042 el golden master se cierra ya en la generación; esta ronda queda como red de seguridad y no se invoca cuando no hay diferencias.
