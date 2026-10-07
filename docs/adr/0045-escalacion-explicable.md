# ADR-0045 — Escalación explicable: código, diferencia y análisis con opciones en la pregunta de intentos agotados

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 10.4 (tarjetas de decisión), 11.1 (verificación en el bucle), 9.2 (agentes)
- **Relacionadas:** ADR-0042 (generación fiel), ADR-0043 (intentos con progreso), ADR-0044 (comparación honesta)

## Contexto

Cuando un paso agota sus intentos, la plataforma pregunta "¿cómo seguimos?" con el diagnóstico crudo y dos
opciones fijas (reintentar, recomendada con confianza 0,5; parar). La persona decide a ciegas: no ve el código que
no pasó, ni qué cambió entre intentos, ni por qué. En las corridas reales las escalaciones se respondían
"reintentar" por inercia y gastaban rondas en causas que ningún intento podía cerrar (una salida nunca asignada,
unas pruebas que no compilaban por sí mismas), mientras el propio desarrollador había descrito la causa en sus
respuestas, que nadie leía.

## Decisión

1. **Evidencia en la pregunta.** Al escalar, el paso adjunta a la pregunta (`evidence`) el diagnóstico, los archivos
   del último intento y la versión anterior de cada uno (la base conservada en la convergencia, el intento previo
   en los demás pasos). El bucle `do_verify_correct` recibe un `explain` del paso, que conoce los archivos; su
   resultado se registra en el journal (`explained/<agente>/<ronda>`) y un fallo al explicar nunca bloquea la
   pregunta: queda con el diagnóstico y las opciones de siempre.
2. **Análisis con opciones.** En las corridas guiadas, una llamada al rol existente `code-reviewer` (prompt
   `escalation-analyst`, sin agente ni asignación nuevos) devuelve la causa en lenguaje claro, qué cambió entre
   intentos y dos o tres respuestas propuestas con su confianza: reintentar, **reintentar con una instrucción**
   concreta (archivo y cambio), o parar. La recomendada es la de mayor confianza y la pregunta lleva esa confianza.
3. **La respuesta dirige la siguiente ronda.** El comentario de la persona, su respuesta libre o la instrucción de
   la opción elegida se añade al diagnóstico que recibe el siguiente intento ("Instruction from the reviewer: …").
   "Parar" cierra la corrida como antes.
4. **Pantalla.** La tarjeta muestra paneles colapsables: análisis (causa, cambio, opciones con estrella y barra de
   confianza), diagnóstico, código del último intento con las líneas que el diagnóstico señala resaltadas, y la
   diferencia con la versión anterior (solo las líneas cambiadas con contexto). Cada opción del desplegable muestra
   su confianza y su instrucción.

## Alternativas consideradas

- Un agente nuevo "analista de escalaciones": exigiría tocar el catálogo de 19 agentes, la matriz de asignación y
  su migración; el revisor de código ya tiene el perfil y la descripción adecuados.
- Analizar también en modo no guiado: cambiaría el número de llamadas de las corridas grabadas si escalaran; se
  deja para cuando el modo no guiado tenga su propia grabación de escalación.
- Un diff en el servidor: el cliente lo calcula sobre las dos versiones, que viajan completas como evidencia.

## Consecuencias

- Una escalación guiada cuesta una llamada más (del orden de 0,05 a 0,15 USD con el perfil de revisión).
- La evidencia puede pesar unas decenas de KB por pregunta (archivos recortados a 60 000 caracteres).
- Las grabaciones no cambian: ninguna corrida grabada escala, y sin modo guiado no hay llamada al analista.

## Cómo se valida

`test_escalation.py` (evidencia, análisis, opción con instrucción, comentario, fallo del analista, parar),
`test_fidelity.py` (la convergencia adjunta su base), `model.test.ts` del web (agrupación de evidencia, diff por
líneas, líneas señaladas), suites de orquestación y worker, y la próxima escalación real en la aplicación.
