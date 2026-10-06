# ADR-0044 — Comparación honesta con el legado: salidas nunca asignadas, llamadas antes de un rechazo y progreso por severidad

- **Estado:** Aceptada · 2026-10-06
- **Secciones:** 11.3 (golden master), 10.3 (generación), 11.1 (verificación en el bucle)
- **Relacionadas:** ADR-0017 (packs), ADR-0042 (generación fiel), ADR-0043 (convergencia persistente; sus
  precisiones P28 y P29 quedan recogidas aquí)

## Contexto

Dos rondas de convergencia (nueve llamadas al desarrollador, ~8 USD) sobre el procedimiento de 2 173 líneas
oscilaron entre dos versiones sin acercarse. El análisis de las peticiones y respuestas guardadas mostró que las
diferencias que dominaban **no las podía corregir ningún desarrollador**:

1. **Un parámetro de salida que el programa nunca asigna.** Se declara `output` en la línea 84 y no vuelve a
   aparecer. Sybase devuelve al llamador el valor que recibió: el golden master lo registró como `0` en los 50
   casos que lo pasaban y como `NULL` en los 23 que no. El arquitecto lo mapeó como salida del caso de uso y la
   comparación lo exigía: 72 de 73 casos "diferían" en él hiciera lo que hiciera el destino. El desarrollador
   alternó entre devolver `0` (22 casos distintos) y `null` (50 casos distintos); toda la "distancia" que la
   plataforma medía era ese ruido, y el propio desarrollador lo registró como hallazgo (`PLATFORM_DIFFERENCE`,
   "nunca se asigna") sin que nadie lo leyera.
2. **Las llamadas anteriores a un rechazo desaparecían.** El legado rechaza con `select @o_error = código` y
   `return` **después** de llamar a otros programas (grabar el movimiento fallido, por ejemplo): 5 casos
   rechazados, los 5 con llamadas. El destino modela el rechazo como excepción (`BusinessError`) y el arnés
   borraba las llamadas al capturarla ("dentro de la transacción revertida no tuvieron efecto"). Así, lanzar la
   excepción daba el código correcto con cero llamadas, y no lanzarla daba las llamadas con código 0: una
   contradicción que el desarrollador describió en su cuarta respuesta y que ninguna corrección resuelve.
3. **La métrica de progreso y la base reconstruida** (P28/P29) amplificaban el ruido: conservaban o descartaban
   versiones por el parámetro fantasma.

## Decisión

1. **Salidas nunca asignadas, enmascaradas.** El adaptador Sybase detecta estáticamente los parámetros `output`
   que ninguna sentencia escribe (`select/set @p =`, `fetch into @p`, `@x = @p output` en una llamada anidada) y
   los registra en el golden master (`unassigned_outputs`, omitido al serializar cuando está vacío: las
   grabaciones no cambian). `masks()` añade la máscara `outputs:@p` con la razón "el programa nunca asigna este
   parámetro: el legado devuelve lo que el llamador pasó" **solo si todos los casos grabados confirman el eco**
   (salida igual a la entrada, o nula cuando no se pasó). El veredicto la lista como lo que no prueba, con su razón.
2. **Las llamadas antes de un rechazo se conservan.** Los arneses (Java en sus tres variantes, .NET y Go) dejan de vaciar la traza al capturar
   `BusinessError`: la traza es lo que hizo el servicio; la reversión deshace las tablas, que se vuelcan después.
   Un rechazo del destino se compara como el del legado: código, mensaje y las llamadas que hizo antes.
3. **El grabador Sybase reporta cada llamada en el momento.** Registraba las llamadas en una tabla y un `rollback`
   del legado las borraba (el mismo punto ciego que el arnés, al revés: en el procedimiento ficticio el débito
   fallido "no llamaba" al débito). El stub emite ahora la llamada como conjunto de resultados al producirse, que
   el cliente ya tiene cuando llega el `rollback`; la tabla queda solo para elegir la respuesta n-ésima. Las cuatro
   grabaciones del fixture y de M4 se regrabaron con Sybase local: cambian únicamente las llamadas de los casos con
   rollback (el débito aparece antes del registro de error), todo lo demás es idéntico.
4. **Progreso por severidad y base reevaluada** (P29). "Más cerca del legado" compara la severidad de los casos
   (cada caso distinto pesa su peor diferencia: caída 5, retorno 4, salida 3, mensaje o tabla 2, llamada 1), luego
   el total de diferencias, luego la distancia por tipo. Tras un reinicio, cada corrección conservada se reevalúa
   sobre el golden master con la regla de hoy antes de aplicarla. El diagnóstico lista los casos que una corrección
   rompió y los que arregló (P28).

## Alternativas consideradas

- Pedir al arquitecto que no mapee salidas no asignadas: útil como pista, pero no basta; la comparación debe ser
  honesta aunque el diseño las mapee (y un diseño aprobado no se rehace por esto).
- Que el desarrollador "eco" el valor de entrada: inventa comportamiento (R04) para imitar un accidente del motor.
- Mantener las llamadas borradas y enmascarar `calls:` en casos rechazados: oculta llamadas reales del legado.

## Consecuencias

- Las aceptaciones grabadas siguen PROVEN: el procedimiento ficticio asigna sus dos salidas; sus rechazos tras un
  débito fallido muestran ahora la llamada al débito en ambos lados, como ocurrió.
- Sobre la corrida real, las 47 diferencias restantes bajan a las de lógica (validación del tipo de cuenta, orden
  de llamadas en los caminos de fallo, un concepto contable), que el desarrollador sí puede corregir con el
  programa a la vista.
- Pendiente: pista al arquitecto guiado para no mapear salidas no asignadas; mismo análisis para los adaptadores
  COBOL y ASPX cuando tengan golden master propio.

## Cómo se valida

`test_golden.py` (detección), `test_equivalence.py` del pack (máscara solo con eco confirmado; serialización sin
el campo vacío; arnés con Docker), `test_fidelity.py` (clave de progreso con las tres correcciones reales, base
reevaluada), aceptaciones M4 a M8b intactas, y la corrida real reintentada desde Generation.
