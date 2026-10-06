# ADR-0043 — Puertos con varias salidas, convergencia persistente e intentos con progreso

- **Estado:** Aceptada · 2026-10-06
- **Secciones:** 6.1 (diseño), 10.3 (generación), 11.1 (verificación en el bucle), 11.3 (golden master)
- **Relacionadas:** ADR-0042 (generación fiel al programa), ADR-0035 (nota pendiente del 2026-10-06), ADR-0034
  (reintento por fase), ADR-0017 (packs)

## Contexto

La validación interna de M24 sobre el procedimiento de 2 173 líneas dejó cuatro bloqueos que no eran del código
generado sino de la plataforma:

1. **Un programa, varias salidas.** `sp_con_confcontable` devuelve dos parámetros de salida en una llamada. El
   modelo de diseño sólo admitía una salida por método (`legacy_output`), así que el arquitecto partió el puerto en
   dos métodos (`findTransaction`, `findCause`) y el destino llamó al programa dos veces: cada llamada posterior
   corría una posición en la traza y los 65 casos diferían en `calls`. La regla "un método por puerto" (P27)
   hizo imposibles los diseños y se retiró.
2. **El estado de la convergencia se perdía al reiniciar el worker.** El journal repetía los intentos del
   desarrollador sin volver a llamar al modelo, pero la base (los archivos de la última corrección conservada) se
   reconstruía desde los archivos generados: la primera comparación tras el reinicio volvía al punto de partida.
3. **Las excepciones del arnés no decían dónde.** `ArithmeticException: Rounding necessary` en 10 casos sin la línea
   del servicio generado que la lanzaba: el desarrollador corregía a ciegas.
4. **Tres intentos por ronda contaban igual el progreso y el estancamiento.** Una corrección conservada (más cerca
   del legado) gastaba un intento como una descartada; con 65 casos y varias causas encadenadas, la ronda se agotaba
   mientras la distancia bajaba de forma monótona.

## Decisión

1. **`PortMethod.legacy_outputs`** (`{campo: @o_parametro}`): un método que devuelve una entidad del diseño cuyos
   campos llevan las salidas del programa. El validador exige que el método devuelva una entidad y que cada clave sea
   un campo de ella. `target_case` añade a cada respuesta del stub `"outputs": {campo: valor}`; los tres arneses
   Java (Spring JDBC, MongoDB, Quarkus) construyen el record (envuelto en `Optional` si el método lo declara) desde
   `outputs`. La guía de diseño guiado (`GUIDED_DESIGN`, solo con `guided_extraction`: el prompt grabado del arquitecto no cambia) lo documenta y la regla guiada **"un puerto que reemplaza un programa tiene
   exactamente un método"** vuelve a `design_problems`, ahora satisfacible.
2. **Convergencia persistente.** `fidelity.rebuild_base` lee del journal los memos `dvc/backend-dev/<i>` y aplica
   de nuevo, en orden, los archivos de los intentos conservados (`ok` o diagnóstico "kept as the new base") antes de
   la primera comparación. Un reinicio del worker continúa desde la última base.
3. **Dónde falló.** El arnés añade a `failure` el primer marco de la pila dentro del paquete base
   (`at pkg.application.XService.method(XService.java:123)`).
4. **Intentos con progreso.** `Verification.progress`: una corrección conservada no cuenta contra
   `max_iterations`; sólo los intentos sin progreso agotan la ronda. Tope absoluto de
   `max_iterations × ATTEMPTS_AT_MOST` (4) intentos por ronda, progreso o no, y después la pregunta de escalado de
   siempre. El evento "started" dice `attempt k of n, after m with progress`.

## Alternativas consideradas

- Mantener un método por salida y masajear la traza de llamadas (agrupar llamadas consecutivas al mismo programa):
  oculta una diferencia real de comportamiento (R11: una llamada, todas las salidas).
- Guardar la base de la convergencia en una tabla propia: el journal ya es el estado del grafo y se persiste con él.
- Subir `max_iterations`: gasta igual en intentos estancados; el progreso es lo que debe comprar intentos.

## Consecuencias

- Los diseños aprobados antes siguen válidos (`legacy_outputs` es opcional); los nuevos diseños guiados deben
  devolver una entidad por programa externo.
- Las aceptaciones grabadas (M4, M6, M8b, M10, M11, M18) no cambian: nada de esto toca el modo no guiado y el
  harness sólo mira `outputs` cuando existe.
- Una ronda puede ser más larga (hasta 12 intentos con `max_iterations = 3`) sólo mientras cada corrección acerca.

## Cómo se valida

`test_fidelity.py` (progreso no gasta intentos, tope absoluto, base reconstruida desde el journal),
`test_generation.py` (validador de `legacy_outputs`, regla de un método por puerto), `test_equivalence.py` del pack
(stubs con `outputs`), y una corrida real reintentada desde Architecture.

## Precisión P28 (2026-10-06): retrocesos en la convergencia

La primera corrida con este ADR conservó una corrección que quitaba cinco caídas pero cambiaba una salida en todos
los casos: 38 casos distintos pasaron a 57 y los intentos siguientes oscilaron entre las dos versiones sin superar
esa base. Desde P28 una corrección se conserva solo si acorta la distancia **y no aumenta los casos distintos**; y
el diagnóstico que vuelve al desarrollador lista los casos que coincidían antes y difieren ahora, los que la
corrección arregló, y aclara que los archivos mostrados son la base conservada, no la versión descartada.
