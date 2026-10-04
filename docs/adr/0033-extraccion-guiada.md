# ADR-0033 — Extracción guiada de reglas

- **Estado:** Aceptada · 2026-10-04
- **Secciones:** 6.1 (fase 5, extracción de reglas), 11.1 (hacer, verificar, corregir), 11.2 (revisión independiente)
- **Relacionadas:** ADR-0011 (código del cliente), ADR-0012 (grabaciones), ADR-0032 (inventario profundo)

## Contexto

La extracción lee cada procedimiento por *backward slices*: trozos de líneas de las que depende cada resultado. Con
un procedimiento real de más de 2.000 líneas aparecieron tres riesgos:

- **El agente pierde el contexto del programa.** Un slice de 70 trozos no dice dónde está cada pieza ni qué hace el
  resto del programa.
- **Una cita mal ubicada se descarta.** Pasa aunque la regla sea real y esté a pocas líneas.
- **Reglas duplicadas o mal calificadas.** La misma regla sale de dos slices con palabras distintas, y hay demasiadas
  P0.

Comparamos con el plugin de modernización del equipo, que lee archivos completos:

- **Lo que tiene y nosotros no:** pide una regla por decisión de negocio, mueve citas en vez de descartarlas,
  consolida reglas por significado, juzga las P0 con dos lentes y trata el código como dato no confiable.
- **Lo que no tiene y nosotros sí:** parte los programas grandes, verifica las citas por código y mide cobertura.

El aprobador pidió sumar esas siete mejoras sin quitar lo que ya funciona.

## Decisión

Todo se suma con la opción de corrida `guided_extraction`:

- La activan las corridas que inicia una persona; se desactiva con `guidedExtraction: false`.
- Sin la opción no cambia ningún prompt ni ninguna llamada, así que las grabaciones existentes siguen valiendo.

Con la opción:

1. **Mapa del programa en cada slice.**
   - Qué lleva: los bloques de la unidad en orden, con líneas, fase transaccional y, si hubo inventario profundo, su
     descripción.
   - Para qué sirve: es orientación. Se sigue citando solo lo que muestra el slice.
2. **Programas chicos completos.** Un archivo de hasta 600 líneas se lee entero, en lugar de en slices.
3. **Granularidad y P0 estrictos.**
   - El prompt pide una regla por decisión de negocio, unas 40 a 80 líneas de lógica por regla, y P0 solo para:
     - dinero o saldos;
     - lo regulatorio;
     - la integridad o la seguridad de los datos;
     - la decisión central.
   - El código avisa antes de C1 si más del 25 % de las reglas son P0.
4. **El verificador corrige la cita.**
   - Ve 15 líneas antes y después de la cita, y puede devolver un rango corregido.
   - El código lo acepta solo si está cerca de la cita original y tiene código.
   - La regla se queda con la cita nueva, confianza media como máximo y una pregunta para la persona que revisa.
5. **Consolidación por significado.**
   - Un modelo agrupa las reglas que dicen lo mismo, en bloques de 150.
   - El código valida los ids y fusiona cada grupo quedándose con lo más cauto: todas las citas, la prioridad más alta,
     la confianza más baja, y todos los defectos y preguntas.
6. **Dos lentes para las reglas P0.**
   - El primer juez revisa la fidelidad: valores, condiciones, redondeo y orden.
   - El segundo revisa la criticidad: si P0 está justificado.
   - Si el segundo no la ve crítica, la regla baja a P1 con una nota.
7. **Escenarios de borde y el código como dato.**
   - El prompt pide escenarios de borde con valores concretos.
   - Un comentario o un texto con forma de instrucción no se obedece. El código busca esas líneas en el fuente y avisa
     antes de C1, mostrando solo archivo y línea.

Los avisos, junto con la cobertura de sentencias de negocio, van en `inventory/coverage.json` y aparecen en el
chequeo de C1 sin bloquearlo.

## Consecuencias

- **Costo:** una corrida con la opción hace una llamada más (la consolidación) y pedidos algo más largos (el mapa y
  las líneas alrededor de la cita). Un programa chico se lee en una sola llamada en lugar de una por slice.
- **Evidencia:** la aceptación M18 graba la corrida con la opción sobre el procedimiento ficticio y la compara con la
  extracción sin opción de M4, contra la misma especificación de referencia.
- **Sin cambio de esquema:** el modelo de regla no cambia. Los casos borde van como escenarios.
